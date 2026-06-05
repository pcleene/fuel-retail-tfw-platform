import json
import logging
import time
from datetime import datetime, timedelta, timezone

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.prompts import FRAUD_ANALYSIS_SYSTEM_PROMPT
from backend.agents.state import FraudAgentState
from backend.config import settings
from backend.database import get_fraud_db

logger = logging.getLogger(__name__)


def _serialize_doc(doc: dict) -> dict:
    """Recursively convert datetime and ObjectId values so the doc is JSON-safe."""
    from bson import ObjectId

    cleaned = {}
    for key, val in doc.items():
        if isinstance(val, datetime):
            cleaned[key] = val.isoformat()
        elif isinstance(val, ObjectId):
            cleaned[key] = str(val)
        elif isinstance(val, dict):
            cleaned[key] = _serialize_doc(val)
        elif isinstance(val, list):
            cleaned[key] = [
                _serialize_doc(item) if isinstance(item, dict)
                else item.isoformat() if isinstance(item, datetime)
                else str(item) if isinstance(item, ObjectId)
                else item
                for item in val
            ]
        else:
            cleaned[key] = val
    return cleaned


async def fraud_analysis_node(state: FraudAgentState) -> dict:
    """Agent 1: Query user profile, recent events, and alerts, then use Claude to analyze fraud patterns."""
    db = get_fraud_db()
    user_id = state["user_id"]
    queries = list(state.get("queries_executed", []))

    # ── Query 1: User profile ────────────────────────────────────────
    t0 = time.monotonic()
    profile_query = {"userId": user_id}
    user_profile = await db["user_profiles"].find_one(profile_query)
    elapsed1 = (time.monotonic() - t0) * 1000

    queries.append({
        "agent": "fraud_analysis",
        "collection": "user_profiles",
        "operation": "find_one",
        "pipeline": {"filter": profile_query},
        "execution_time_ms": round(elapsed1, 1),
        "docs_returned": 1 if user_profile else 0,
        "mongodb_features": ["Document Model"],
    })

    # ── Query 2: Recent events (last 7 days) ─────────────────────────
    t1 = time.monotonic()
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    events_query = {"user_id": user_id, "timestamp": {"$gte": seven_days_ago}}
    events_cursor = db["events"].find(events_query).sort("timestamp", -1).limit(50)
    recent_events = []
    async for doc in events_cursor:
        recent_events.append(_serialize_doc(doc))
    elapsed2 = (time.monotonic() - t1) * 1000

    queries.append({
        "agent": "fraud_analysis",
        "collection": "events",
        "operation": "find",
        "pipeline": {
            "filter": {"user_id": user_id, "timestamp": {"$gte": "7_days_ago"}},
            "sort": {"timestamp": -1},
            "limit": 50,
        },
        "execution_time_ms": round(elapsed2, 1),
        "docs_returned": len(recent_events),
        "mongodb_features": ["Secondary Index", "Sort", "Limit"],
    })

    # ── Query 3: Fraud alerts ────────────────────────────────────────
    t2 = time.monotonic()
    alerts_query = {"userId": user_id}
    alerts_cursor = db["fraud_alerts"].find(alerts_query).sort("createdAt", -1).limit(20)
    fraud_alerts = []
    async for doc in alerts_cursor:
        fraud_alerts.append(_serialize_doc(doc))
    elapsed3 = (time.monotonic() - t2) * 1000

    queries.append({
        "agent": "fraud_analysis",
        "collection": "fraud_alerts",
        "operation": "find",
        "pipeline": {
            "filter": {"userId": user_id},
            "sort": {"createdAt": -1},
            "limit": 20,
        },
        "execution_time_ms": round(elapsed3, 1),
        "docs_returned": len(fraud_alerts),
        "mongodb_features": ["Secondary Index", "Sort", "Limit"],
    })

    # ── Prepare context for Claude ───────────────────────────────────
    profile_safe = _serialize_doc(user_profile) if user_profile else {}
    # Remove embedding from context to save tokens
    if "fraud" in profile_safe and "embedding" in profile_safe.get("fraud", {}):
        profile_safe["fraud"].pop("embedding", None)

    context = f"""User ID: {user_id}

=== USER PROFILE ===
{json.dumps(profile_safe, indent=2, default=str)}

=== RECENT EVENTS (last 7 days, up to 50) ===
{json.dumps(recent_events[:25], indent=2, default=str)}

=== FRAUD ALERTS ===
{json.dumps(fraud_alerts, indent=2, default=str)}
"""

    # ── Call Claude for fraud analysis ────────────────────────────────
    llm = ChatAnthropic(
        model="claude-sonnet-4-20250514",
        api_key=settings.anthropic_api_key,
        max_tokens=1024,
        temperature=0,
    )
    response = await llm.ainvoke([
        SystemMessage(content=FRAUD_ANALYSIS_SYSTEM_PROMPT),
        HumanMessage(content=context),
    ])

    try:
        fraud_analysis = json.loads(response.content)
    except json.JSONDecodeError:
        text = response.content
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            fraud_analysis = json.loads(text[start:end])
        else:
            fraud_analysis = {
                "fraud_pattern": "unknown",
                "confidence": 0.5,
                "timeline_analysis": [],
                "key_indicators": [],
                "false_positive_likelihood": 0.5,
                "affected_amount_myr": 0.0,
            }

    return {"fraud_analysis": fraud_analysis, "queries_executed": queries}
