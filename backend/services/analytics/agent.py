"""
Agent runner: system prompt, persistent MCP session, and ask_question entry point.
"""

import asyncio
import re
import time
import logging

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langgraph.prebuilt import create_react_agent

from backend.config import settings
from backend.services.analytics.memory import (
    get_checkpointer,
    get_memory_store,
    build_memory_tools,
)
from backend.services.analytics.conversations import save_conversation_turn

logger = logging.getLogger(__name__)


# ─── FuelRetail Terminology System Prompt ───────────────────────────────

SYSTEM_PROMPT = """You are FuelRetail's analytics assistant. You answer business questions about FuelRetail's user data by querying MongoDB.

## IMPORTANT: You are already connected to MongoDB
- The MongoDB MCP Server is pre-configured and already connected. Do NOT ask for a connection string.
- Do NOT call the "connect" tool — the connection is already established via environment variable.
- Go straight to querying: use find, count, aggregate, collection-schema, etc.

## Database Context
- Database: FuelRetail_screening
- Primary collection: user_profiles (approximately 10,000 documents)
- Secondary collection: sanctioned_list (50+ documents)

## FuelRetail Terminology Mappings
When the user says these terms, map them to the corresponding MongoDB fields:

| Term | Meaning | Field(s) |
|---|---|---|
| "MAU" / "monthly active users" | Users with at least 1 transaction in last 30 days | activitySummary.lastTransactionAt |
| "new users" | Users created in the specified period | createdAt |
| "active users" | Users with status "active" | status |
| "verified users" | Users with KYC verified | kyc.status = "verified" |
| "premium users" | Users on premium wallet tier | wallet.tier = "premium" |
| "flagged users" | Users flagged by screening | screening.riskFlag = true |
| "high-risk" / "risky users" | Users with high KYC risk level | kyc.riskLevel = "high" |
| "churn" / "churned users" | Users active last month but not this month | activitySummary.lastTransactionAt |
| "big spenders" | Users with high monthly average spend | activitySummary.monthlyAvgSpend |
| "dormant" | Users with no transactions in 60+ days | activitySummary.lastTransactionAt |

## Currency
All monetary values are in MYR (Malaysian Ringgit). Format as "RM X,XXX.XX".

## Response Rules
1. ALWAYS show the MQL query you generated in a ```javascript code block BEFORE showing results
2. Label the code block clearly as "Generated MQL"
3. Format numbers with commas (e.g., 10,000 not 10000)
4. Format currency as RM with 2 decimal places
5. For percentages, show 1 decimal place
6. Keep responses concise but informative
7. If the question is ambiguous, state your interpretation before querying
8. Use the count tool for simple counts, find for document lookups, and aggregate for grouped/computed results
9. Do NOT use $regex in queries unless the user explicitly asks for case-sensitive pattern matching
10. Today's date for relative time calculations: use the current UTC date

## Long-Term Memory (IMPORTANT)
You have two memory tools: `save_memory` and `recall_memories`. You MUST use them.

**RULE: When the user says "remember", "always", "my preference", or shares a reusable fact,
you MUST call `save_memory` BEFORE responding.** Do not just acknowledge — actually call the tool.

**save_memory(key, content):**
- key: short snake_case identifier (e.g. "format_preference", "compliance_threshold")
- content: the information to remember
- Example: User says "Remember I want percentages"
  -> CALL save_memory(key="format_preference", content="Always display results as percentages, not raw counts")
  -> THEN respond confirming you saved it

**recall_memories(query):**
- Call this BEFORE answering any analytics question to check for user preferences
- query: natural language description of what to look for
- Example: Before answering "how many active users?" -> call recall_memories(query="user preferences formatting")
  -> If it returns a formatting preference, apply it to your answer

**Key rules:**
- ALWAYS call save_memory when the user asks you to remember something — do not skip it
- ALWAYS call recall_memories before answering analytics questions
- If recall returns preferences, apply them silently unless the user asks about memories
"""


# ─── Stats ────────────────────────────────────────────────────────

_stats = {"totalQueries": 0, "totalLatencyMs": 0.0}


def get_stats() -> dict:
    """UI-only: in-memory counters displayed in the frontend stats dashboard."""
    total = _stats["totalQueries"]
    return {
        "totalQueries": total,
        "activeSessions": 0,
        "avgLatencyMs": round(_stats["totalLatencyMs"] / total, 0) if total > 0 else 0,
    }


# ─── Persistent MCP Session ───────────────────────────────────────

class _MCPSession:
    def __init__(self):
        self._session: ClientSession | None = None
        self._cm_stack: list = []
        self._lock = asyncio.Lock()

    async def get_tools(self):
        session = await self._ensure_session()
        return await load_mcp_tools(session)

    async def _ensure_session(self) -> ClientSession:
        async with self._lock:
            if self._session is not None:
                return self._session

            logger.info("Starting persistent MCP session...")
            params = StdioServerParameters(
                command=settings.mcp_server_command,
                args=settings.mcp_server_args,
                env={"MDB_MCP_CONNECTION_STRING": settings.mcp_connection_string},
            )
            stdio_cm = stdio_client(params)
            read, write = await stdio_cm.__aenter__()
            self._cm_stack.append(stdio_cm)

            session_cm = ClientSession(read, write)
            session = await session_cm.__aenter__()
            self._cm_stack.append(session_cm)

            await session.initialize()
            self._session = session
            logger.info("MCP session ready")
            return session

    async def close(self):
        """Tear down the MCP session and stdio subprocess in reverse order."""
        async with self._lock:
            self._session = None
            while self._cm_stack:
                cm = self._cm_stack.pop()
                try:
                    await cm.__aexit__(None, None, None)
                except Exception as e:
                    logger.debug("MCP cleanup (expected): %s", e)
            logger.info("MCP session closed")


_mcp = _MCPSession()


async def close_mcp():
    await _mcp.close()


# ─── Agent Runner ──────────────────────────────────────────────────

EXCLUDED_TOOLS = {
    "connect", "atlas-local-connect-deployment", "atlas-local-list-deployments",
    "list-knowledge-sources", "search-knowledge", "mongodb-logs",
}


async def ask_question(question: str, session_id: str, user_id: str = "analyst-1") -> dict:
    """Run a natural language question through the LangChain agent with MCP tools."""
    start = time.time()

    all_tools = await _mcp.get_tools()
    tools = [t for t in all_tools if t.name not in EXCLUDED_TOOLS]

    memory_tools = build_memory_tools(user_id)
    tools.extend(memory_tools)
    logger.info("Agent tools: %d MCP + %d memory = %d total",
                len(tools) - len(memory_tools), len(memory_tools), len(tools))

    model = ChatBedrockConverse(
        model=settings.bedrock_model_id,
        region_name=settings.bedrock_region,
        max_tokens=4096,
    )

    agent = create_react_agent(
        model=model,
        tools=tools,
        checkpointer=get_checkpointer(),
        store=get_memory_store(),
        prompt=SYSTEM_PROMPT,
    )

    config = {
        "configurable": {
            "thread_id": session_id,
            "user_id": user_id,
        }
    }
    result = await agent.ainvoke(
        {"messages": [HumanMessage(content=question)]},
        config=config,
    )

    final_message = result["messages"][-1]
    answer = final_message.content if hasattr(final_message, "content") else str(final_message)

    latency_ms = round((time.time() - start) * 1000, 0)
    mql = _extract_mql(answer)
    memory_trace = _extract_memory_trace(result["messages"])

    _stats["totalQueries"] += 1
    _stats["totalLatencyMs"] += latency_ms

    asyncio.create_task(
        save_conversation_turn(session_id, user_id, question, answer, mql, latency_ms)
    )

    return {
        "answer": answer,
        "mql": mql,
        "latency_ms": latency_ms,
        "session_id": session_id,
        "memory_trace": memory_trace,
    }


def _extract_mql(text: str) -> str | None:
    """Extract MQL code block from the agent's response.

    UI-only: the frontend renders this in a dedicated "Generated MQL" panel alongside the answer.
    """
    pattern = r"```(?:javascript|js|mql)\s*\n(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    return matches[0].strip() if matches else None


MEMORY_TOOL_NAMES = {"save_memory", "recall_memories"}


def _extract_memory_trace(messages: list) -> list[dict]:
    """Walk the agent message trace and extract memory tool call/result pairs.

    UI-only: powers the "Memory Activity" panel in the frontend that shows
    save_memory / recall_memories calls and their results.
    """
    # Build a map of tool_call_id → call info from AIMessages
    pending: dict[str, dict] = {}
    trace: list[dict] = []

    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                if tc["name"] in MEMORY_TOOL_NAMES:
                    pending[tc["id"]] = {
                        "tool": tc["name"],
                        "input": tc["args"],
                    }
        elif isinstance(msg, ToolMessage) and msg.tool_call_id in pending:
            entry = pending.pop(msg.tool_call_id)
            entry["output"] = msg.content
            trace.append(entry)

    return trace
