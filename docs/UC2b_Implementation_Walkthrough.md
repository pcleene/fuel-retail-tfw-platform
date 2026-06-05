# UC2b — Analytics Chatbot: End-to-End Implementation Walkthrough

## Overview

This document walks through the implementation of the **Natural Language Analytics Chatbot** built for FuelRetail's Technical Field Workshop. The chatbot allows analysts to ask business questions in plain English and get real answers from MongoDB — with **zero embeddings, zero query templates, and zero vector databases**.

The key technologies:

| Component | Technology | Role |
|---|---|---|
| **LLM** | Claude (via AWS Bedrock) | Reasoning engine — translates questions to MQL |
| **MCP Server** | MongoDB MCP Server (`mongodb-mcp-server`) | Bridge between the LLM and MongoDB |
| **Agent Framework** | LangChain + LangGraph | Orchestrates the ReAct agent loop |
| **Backend** | FastAPI (Python) | API layer |
| **Database** | MongoDB Atlas | Data source (10,000 user documents) |
| **Frontend** | SvelteKit 5 | Chat UI |

---

## Architecture

```
 User asks: "How many users have verified KYC?"
                    │
                    ▼
┌─────────────────────────────────────────────┐
│  SvelteKit Frontend (localhost:5173)         │
│  POST /api/analytics/ask                    │
└──────────────────┬──────────────────────────┘
                   │ HTTP
                   ▼
┌─────────────────────────────────────────────┐
│  FastAPI Backend (localhost:8002)            │
│                                             │
│  ┌────────────────────────────────────────┐ │
│  │  LangChain ReAct Agent                 │ │
│  │  Model: Claude via AWS Bedrock         │ │
│  │  Tools: loaded from MCP Server         │ │
│  └──────────────┬─────────────────────────┘ │
└─────────────────┼───────────────────────────┘
                  │ MCP Protocol (stdio)
                  ▼
┌─────────────────────────────────────────────┐
│  MongoDB MCP Server                         │
│  Tools: find, count, aggregate,             │
│         collection-schema, list-collections │
└──────────────────┬──────────────────────────┘
                   │ MongoDB Wire Protocol
                   ▼
┌─────────────────────────────────────────────┐
│  MongoDB Atlas                              │
│  Cluster: <atlas-cluster>.mongodb.net     │
│  Database: FuelRetail_screening                  │
│  Collection: user_profiles (10,000 docs)    │
│  Auth: X.509 Certificate                   │
└─────────────────────────────────────────────┘
```

---

## 1. MongoDB Connection — X.509 Certificate Auth

The MongoDB Atlas cluster uses **X.509 certificate authentication** (no username/password). This connection string is shared with the MCP Server so it can query the database on behalf of the LLM agent.

**`backend/config.py`**

```python
class Settings(BaseSettings):
    # MongoDB MCP Server configuration
    mcp_server_command: str = "/opt/homebrew/bin/mongodb-mcp-server"
    mcp_server_args: list[str] = ["--readOnly"]
    mcp_connection_string: str = (
        "mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>"
        "?authSource=%24external"
        "&authMechanism=MONGODB-X509"
        "&tls=true"
        "&tlsCertificateKeyFile=<local-path>"
        "&appName=testCluster"
    )

    # AWS Bedrock (Claude)
    bedrock_region: str = "ap-southeast-1"
    bedrock_model_id: str = "apac.anthropic.claude-sonnet-4-20250514-v1:0"
```

Key points:
- **`authMechanism=MONGODB-X509`** — certificate-based auth, no password in the connection string
- **`tlsCertificateKeyFile`** — path to the X.509 PEM certificate
- **`--readOnly`** — MCP server is launched in read-only mode so the demo cannot modify data
- **`/FuelRetail_screening`** — defaults the MCP server to UC1's database

---

## 2. MongoDB MCP Server — The Bridge

The [MongoDB MCP Server](https://github.com/mongodb-js/mongodb-mcp-server) is an open-source server that exposes MongoDB operations as **MCP tools**. It runs as a **stdio subprocess** — the Python backend spawns it and communicates over stdin/stdout using the MCP protocol.

### How it starts

The MCP server is configured with `StdioServerParameters` and launched by our persistent session manager:

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

def _get_server_params() -> StdioServerParameters:
    return StdioServerParameters(
        command=settings.mcp_server_command,       # /opt/homebrew/bin/mongodb-mcp-server
        args=settings.mcp_server_args,             # ["--readOnly"]
        env={
            "MDB_MCP_CONNECTION_STRING": settings.mcp_connection_string
        },
    )
```

The connection string is passed as an **environment variable** (`MDB_MCP_CONNECTION_STRING`) to the subprocess. The MCP server uses it to connect to MongoDB Atlas.

### Tools exposed by the MCP Server

Once connected, the MCP server exposes these tools to the LLM agent:

| MCP Tool | Purpose | Example Usage |
|---|---|---|
| `find` | Query documents with filter, projection, sort, limit | Top 10 users by balance |
| `count` | Count documents matching a filter | "How many verified users?" |
| `aggregate` | Run aggregation pipelines | Group by status, compute averages |
| `collection-schema` | Infer document schema from sample | Agent learns the field structure |
| `list-collections` | List all collections in a database | Agent discovers what data exists |
| `list-databases` | List available databases | Initial exploration |
| `db-stats` | Database-level statistics | Collection sizes |
| `explain` | Query execution plan | Show index usage |

The agent **does not need pre-built query templates**. It reads the schema via `collection-schema`, understands the document structure, and generates correct MQL for any question.

---

## 3. Persistent MCP Session Manager

A critical implementation detail: we maintain a **persistent MCP session** that stays alive across HTTP requests. This avoids re-spawning the MCP server subprocess on every question.

**`backend/services/analytics_service.py`**

```python
class MCPSessionManager:
    """
    Keeps a persistent MCP stdio session alive so we don't hit the
    Python 3.14 + anyio BrokenResourceError on every request.
    """

    def __init__(self):
        self._session: ClientSession | None = None
        self._cm_stack: list = []
        self._lock = asyncio.Lock()

    async def get_session(self) -> ClientSession:
        async with self._lock:
            if self._session is not None:
                return self._session

            logger.info("Starting persistent MCP session...")
            params = _get_server_params()

            # Enter the context managers manually and keep them alive
            stdio_cm = stdio_client(params)
            read, write = await stdio_cm.__aenter__()
            self._cm_stack.append(stdio_cm)

            session_cm = ClientSession(read, write)
            session = await session_cm.__aenter__()
            self._cm_stack.append(session_cm)

            await session.initialize()
            self._session = session

            # Pre-connect to MongoDB so the agent doesn't have to
            try:
                connect_result = await session.call_tool("connect", {
                    "connectionString": settings.mcp_connection_string
                })
                logger.info("MCP pre-connected to MongoDB")
            except Exception as e:
                logger.warning(f"MCP pre-connect attempt: {e}")

            return session
```

What this does:

1. **Spawns the MCP server** as a stdio subprocess (once, on first request)
2. **Initializes the MCP session** — handshake, capability exchange
3. **Pre-connects to MongoDB** by calling the `connect` tool — so the LLM agent can immediately start querying without needing to connect itself
4. **Keeps the session alive** across requests using a lock to prevent race conditions
5. **Auto-recovers** if the session dies (reset + reconnect on failure)

### Tool delegation

Each MCP tool is wrapped as a LangChain `StructuredTool` so the agent can call it:

```python
async def call_tool(self, name: str, arguments: dict) -> Any:
    session = await self.get_session()
    try:
        result = await session.call_tool(name, arguments)
        # Extract text content from MCP result
        texts = []
        for block in result.content:
            if hasattr(block, "text"):
                texts.append(block.text)
        return "\n".join(texts) if texts else str(result.content)
    except Exception as e:
        # Session may be dead — reset and retry once
        logger.warning(f"MCP call failed ({e}), resetting session...")
        await self._reset()
        session = await self.get_session()
        result = await session.call_tool(name, arguments)
        # ... extract text ...
```

---

## 4. AWS Bedrock Integration — Claude as the Reasoning Engine

Instead of calling the Anthropic API directly, we use **AWS Bedrock** with SSO authentication. This means:

- No API key management — uses existing AWS IAM/SSO credentials
- Runs through Bedrock's APAC endpoint in `ap-southeast-1`
- Uses an **inference profile** for the Claude model

### Model configuration

```python
from langchain_aws import ChatBedrockConverse

model = ChatBedrockConverse(
    model=settings.bedrock_model_id,   # "apac.anthropic.claude-sonnet-4-20250514-v1:0"
    region_name=settings.bedrock_region, # "ap-southeast-1"
    max_tokens=4096,
)
```

Key detail: the model ID uses an **APAC inference profile** (`apac.anthropic.claude-sonnet-4-20250514-v1:0`), not the raw model ID. This is required because the raw model ID (`anthropic.claude-sonnet-4-20250514-v1:0`) is not directly available in the APAC region — it must go through an inference profile.

### Authentication flow

```
AWS SSO login (browser)
        │
        ▼
~/.aws/credentials (temporary session token)
        │
        ▼
boto3 picks up credentials automatically
        │
        ▼
ChatBedrockConverse → Bedrock API (ap-southeast-1)
        │
        ▼
Claude Sonnet processes the request
```

No API keys in code or environment variables. `boto3` (used internally by `langchain-aws`) picks up the SSO session credentials from `~/.aws/credentials` automatically.

---

## 5. The LangChain ReAct Agent — Putting It All Together

The agent is the orchestration layer. It receives a question, decides which MCP tools to call, interprets the results, and formats a response.

**`backend/services/analytics_service.py` — `ask_question()`**

```python
async def ask_question(question: str, session_id: str) -> dict:
    start = time.time()

    # 1. Build conversation history for follow-up questions
    history_messages = []
    for exchange in store.get_history(session_id)[-10:]:
        history_messages.append(HumanMessage(content=exchange["question"]))
        history_messages.append(AIMessage(content=exchange["answer"]))

    # 2. Get MCP tools (exclude connect — we pre-connected)
    EXCLUDED_TOOLS = {
        "connect",
        "atlas-local-connect-deployment",
        "atlas-local-list-deployments",
        "list-knowledge-sources",
        "search-knowledge",
        "mongodb-logs",
    }
    tool_specs = await mcp_manager.list_tools()
    tools = [
        _make_langchain_tool(spec)
        for spec in tool_specs
        if spec["name"] not in EXCLUDED_TOOLS
    ]

    # 3. Create the agent with Claude via Bedrock
    model = ChatBedrockConverse(
        model=settings.bedrock_model_id,
        region_name=settings.bedrock_region,
        max_tokens=4096,
    )

    agent = create_react_agent(model=model, tools=tools)

    # 4. Run the agent with system prompt + history + question
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        *history_messages,
        HumanMessage(content=question),
    ]

    result = await agent.ainvoke({"messages": messages})

    # 5. Extract answer and MQL
    final_message = result["messages"][-1]
    answer = final_message.content

    latency_ms = round((time.time() - start) * 1000, 0)
    mql = _extract_mql(answer)

    # 6. Store in session for follow-up context
    store.add_exchange(session_id, question, answer, mql, latency_ms)

    return {
        "answer": answer,
        "mql": mql,
        "latency_ms": latency_ms,
        "session_id": session_id,
    }
```

### What happens during `agent.ainvoke()`:

The ReAct (Reason + Act) loop works like this:

```
Question: "What's the average wallet balance of high-risk users?"
    │
    ▼
THOUGHT: I need to find users where kyc.riskLevel is "high"
         and compute the average of wallet.balance.
         I'll use the aggregate tool.
    │
    ▼
ACTION: call MCP tool "aggregate"
        database: "FuelRetail_screening"
        collection: "user_profiles"
        pipeline: [
          { "$match": { "kyc.riskLevel": "high" } },
          { "$group": { "_id": null, "avgBalance": { "$avg": "$wallet.balance" } } }
        ]
    │
    ▼
OBSERVATION: [{ "_id": null, "avgBalance": 487.23 }]
    │
    ▼
ANSWER: The average wallet balance of high-risk users is **RM 487.23**.
```

The agent may call multiple tools in sequence — for example, calling `collection-schema` first to understand the document structure, then `aggregate` to run the query.

---

## 6. MCP Tool Wrapping — MCP to LangChain

Each MCP tool must be converted to a LangChain `StructuredTool` so the agent can use it. This conversion builds a Pydantic model from the MCP tool's JSON schema:

```python
def _make_langchain_tool(tool_spec: dict):
    """Create a LangChain tool that delegates to the persistent MCP session."""
    name = tool_spec["name"]
    description = tool_spec["description"]
    schema = tool_spec.get("inputSchema", {})

    from langchain_core.tools import StructuredTool
    from pydantic import create_model, Field

    # Build a Pydantic model from the MCP input schema
    fields = {}
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    for prop_name, prop_schema in properties.items():
        prop_type = str  # default
        type_str = prop_schema.get("type", "string")
        if type_str == "integer":    prop_type = int
        elif type_str == "number":   prop_type = float
        elif type_str == "boolean":  prop_type = bool
        elif type_str == "object":   prop_type = dict
        elif type_str == "array":    prop_type = list

        prop_desc = prop_schema.get("description", "")
        if prop_name in required:
            fields[prop_name] = (prop_type, Field(description=prop_desc))
        else:
            fields[prop_name] = (Optional[prop_type], Field(default=None, description=prop_desc))

    InputModel = create_model(f"{name}_input", **fields)

    async def _run(**kwargs):
        args = {k: v for k, v in kwargs.items() if v is not None}
        return await mcp_manager.call_tool(name, args)

    return StructuredTool(
        name=name,
        description=description,
        func=lambda **kw: None,  # sync stub (not used)
        coroutine=_run,          # async execution
        args_schema=InputModel,
    )
```

This means any tool the MCP server exposes is automatically available to the agent — no manual tool definitions needed. If MongoDB MCP Server adds new tools in a future version, they're picked up automatically.

---

## 7. System Prompt — Teaching the Agent Fuel Retail's Language

The system prompt gives the agent domain context so it can translate business terms to MongoDB fields:

```python
SYSTEM_PROMPT = """You are FuelRetail's analytics assistant. You answer business
questions about FuelRetail's user data by querying MongoDB.

## IMPORTANT: You are already connected to MongoDB
- Do NOT call the "connect" tool — the connection is already established.
- Go straight to querying: use find, count, aggregate, etc.

## Database Context
- Database: FuelRetail_screening
- Primary collection: user_profiles (approximately 10,000 documents)

## Fuel Retail Terminology Mappings
| Term                    | Field(s)                          |
|-------------------------|-----------------------------------|
| "MAU"                   | activitySummary.lastTransactionAt |
| "active users"          | status = "active"                 |
| "verified users"        | kyc.status = "verified"           |
| "premium users"         | wallet.tier = "premium"           |
| "flagged users"         | screening.riskFlag = true         |
| "high-risk"             | kyc.riskLevel = "high"            |
| "big spenders"          | activitySummary.monthlyAvgSpend   |

## Response Rules
1. ALWAYS show the MQL in a ```javascript code block
2. Format currency as RM with 2 decimal places
3. Format numbers with commas (10,000 not 10000)
"""
```

This prompt is the only configuration needed to add new business terms — no code changes, no redeployment.

---

## 8. FastAPI Backend — Standalone Analytics Service

The analytics chatbot runs as its own FastAPI service on **port 8002**, independent from the other use cases (fraud on 8000, screening on 8003).

**`backend/main_analytics.py`**

```python
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="FuelRetail Demo — Analytics Chatbot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from backend.routers import analytics
app.include_router(analytics.router)

@app.get("/health")
async def health():
    return {"status": "ok", "service": "analytics"}
```

### API Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/analytics/ask` | Send a question, get an answer + MQL |
| `GET` | `/api/analytics/history/{session_id}` | Retrieve conversation history |
| `GET` | `/api/analytics/terminology` | Get business term mappings |
| `GET` | `/api/analytics/stats` | Query count, avg latency, sessions |

### Example request/response

**Request:**
```bash
curl -X POST http://localhost:8002/api/analytics/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "How many users are in the system?", "session_id": "demo-1"}'
```

**Response:**
```json
{
  "answer": "```javascript\n// Generated MQL\ndb.user_profiles.count()\n```\n\nThere are **10,000** users in the system.",
  "mql": "// Generated MQL\ndb.user_profiles.count()",
  "latency_ms": 4404.0,
  "session_id": "demo-1"
}
```

---

## 9. End-to-End Data Flow

Here's what happens when a user asks **"What's the average wallet balance of high-risk users?"**:

### Step 1 — Frontend sends the question

```typescript
// frontend/src/lib/api.ts
const res = await fetch('http://localhost:8002/api/analytics/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        question: "What's the average wallet balance of high-risk users?",
        session_id: "abc-123"
    })
});
```

### Step 2 — FastAPI receives and delegates to the agent

```python
# backend/routers/analytics.py
@router.post("/ask", response_model=AskResponse)
async def ask(request: AskRequest):
    session_id = request.session_id or str(uuid.uuid4())
    result = await analytics_service.ask_question(request.question, session_id)
    return AskResponse(**result)
```

### Step 3 — Agent gets MCP tools and reasons

The `ask_question()` function:
1. Loads MCP tools from the persistent session (find, count, aggregate, etc.)
2. Creates a `ChatBedrockConverse` model (Claude via Bedrock)
3. Builds a `create_react_agent` with the system prompt + conversation history
4. Calls `agent.ainvoke()` — the ReAct loop begins

### Step 4 — Agent calls MCP tools

The agent decides to use the `aggregate` tool:

```
Agent → MCP Server (stdio): call "aggregate"
  database: "FuelRetail_screening"
  collection: "user_profiles"
  pipeline: [
    { "$match": { "kyc.riskLevel": "high" } },
    { "$group": { "_id": null, "avgBalance": { "$avg": "$wallet.balance" } } }
  ]

MCP Server → MongoDB Atlas (wire protocol): db.user_profiles.aggregate([...])

MongoDB Atlas → MCP Server: [{ "_id": null, "avgBalance": 487.23 }]

MCP Server → Agent (stdio): "Average balance: 487.23"
```

### Step 5 — Agent formats the answer

Claude formats the response with the MQL and the result:

```markdown
```javascript
// Generated MQL
db.user_profiles.aggregate([
  { $match: { "kyc.riskLevel": "high" } },
  { $group: { _id: null, avgBalance: { $avg: "$wallet.balance" } } }
])
```

The average wallet balance of high-risk users is **RM 487.23**.
```

### Step 6 — Frontend renders

The chat UI displays:
- The formatted answer in a message bubble
- A collapsible "View MQL" toggle showing the generated query
- A latency badge (e.g., "4.4s")

---

## 10. Why This Approach Works

### MCP vs RAG for Analytics

```
RAG Approach (current SettleGPT):
  Redshift → Embed queries → Vector DB → LLM → Generate SQL → Execute → Format
  (6 steps, ongoing maintenance, limited to pre-stored patterns)

MCP Approach (this implementation):
  MongoDB → MCP Server → LLM → Done
  (3 steps, zero maintenance, unlimited query coverage)
```

| Aspect | RAG | MCP |
|---|---|---|
| **Infrastructure** | Embedding model + vector index + query templates | Single MCP server binary |
| **Query coverage** | Limited to pre-stored patterns | Any question the LLM can translate |
| **New collection** | Requires new templates + re-embedding | Automatic — schema discovery |
| **Maintenance** | Must curate query templates | Zero |
| **Time to deploy** | Days to weeks | Hours |

### MongoDB's Embedded Document Model

The `user_profiles` collection stores everything in a single document — KYC, wallet, cards, activity, screening. This means:

- **No JOINs needed** — a cross-domain query like "flagged users with premium wallets" is a single `find` with a compound filter
- **The MCP server reads the schema once** and the LLM understands the full document structure
- **Any combination of fields** can be queried without pre-built templates

---

## Running the Demo

### Prerequisites

1. MongoDB Atlas cluster with X.509 certificate auth configured
2. UC1 seed data loaded (10,000 user profiles in `FuelRetail_screening.user_profiles`)
3. AWS SSO session active (`aws sso login`)
4. `mongodb-mcp-server` installed (`npm install -g mongodb-mcp-server`)
5. Python dependencies installed (`pip install -r requirements.txt`)

### Start the services

```bash
# Terminal 1 — Analytics backend (port 8002)
cd FuelRetail-Demo
.venv/bin/uvicorn backend.main_analytics:app --host 0.0.0.0 --port 8002

# Terminal 2 — Frontend (port 5173)
cd frontend
npm run dev
```

### Verify

```bash
# Health check
curl http://localhost:8002/health
# → {"status":"ok","service":"analytics"}

# Test a question
curl -X POST http://localhost:8002/api/analytics/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"How many users are registered?"}'
# → {"answer":"...10,000...","mql":"...","latency_ms":4200,"session_id":"..."}
```

Open `http://localhost:5173/analytics` and click any example chip to start the demo.

---

## File Structure

```
FuelRetail-Demo/
├── backend/
│   ├── config.py                    # MCP + Bedrock settings
│   ├── main_analytics.py            # Standalone FastAPI app (port 8002)
│   ├── routers/
│   │   └── analytics.py             # API endpoints
│   ├── models/
│   │   └── analytics.py             # Pydantic request/response models
│   └── services/
│       └── analytics_service.py     # MCP session manager + LangChain agent
├── frontend/
│   ├── src/lib/api.ts               # Analytics API client
│   └── src/routes/analytics/
│       └── +page.svelte             # Chat UI
└── docs/
    └── UC2b_Implementation_Walkthrough.md  # This document
```
