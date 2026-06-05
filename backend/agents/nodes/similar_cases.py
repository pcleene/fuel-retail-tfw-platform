import json
import logging
import time
from datetime import datetime

from bson import ObjectId
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.prompts import SIMILAR_CASES_SYSTEM_PROMPT
from backend.agents.state import FraudAgentState
from backend.config import settings
from backend.database import get_fraud_db
from backend.services.fraud_service import generate_fraud_embedding

logger = logging.getLogger(__name__)


def _serialize_doc(doc: dict) -> dict:
    """Recursively convert datetime and ObjectId values so the doc is JSON-safe."""
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


async def similar_cases_node(state: FraudAgentState) -> dict:
    """Agent 2: Vector search for similar fraud profiles using Atlas Vector Search."""
    db = get_fraud_db()
    user_id = state["user_id"]
    fraud_analysis = state.get("fraud_analysis", {})
    queries = list(state.get("queries_executed", []))

    # ── Build search text from fraud analysis ────────────────────────
    fraud_pattern = fraud_analysis.get("fraud_pattern", "suspicious activity")
    indicators_text = " ".join(
        ind.get("description", "") for ind in fraud_analysis.get("key_indicators", [])
    )
    search_text = f"{fraud_pattern} {indicators_text}"

    # ── Generate embedding via Voyage AI ─────────────────────────────
    query_embedding = await generate_fraud_embedding(search_text)
    if not query_embedding:
        logger.warning("Failed to generate embedding for similar cases search")
        return {"similar_cases": {"similar_profiles": [], "ring_analysis": {}, "pattern_frequency": {}, "typical_resolution": {}}, "queries_executed": queries}

    # ── Vector search on user_profiles ───────────────────────────────
    t0 = time.monotonic()
    vector_pipeline = [
        {
            "$vectorSearch": {
                "index": "fraud_similarity_index",
                "path": "fraud.embedding",
                "queryVector": query_embedding,
                "numCandidates": 50,
                "limit": 6,
                "filter": {"fraud.riskLevel": {"$ne": "low"}},
            }
        },
        {"$match": {"userId": {"$ne": user_id}}},
        {
            "$addFields": {
                "similarityScore": {"$meta": "vectorSearchScore"},
            }
        },
        {
            "$project": {
                "_id": 0,
                "userId": 1,
                "fullName": 1,
                "status": 1,
                "fraud.riskLevel": 1,
                "fraud.signalsSeen": 1,
                "fraud.alertCount": 1,
                "fraud.lastAlertAt": 1,
                "kyc.riskLevel": 1,
                "wallet.tier": 1,
                "activitySummary": 1,
                "similarityScore": 1,
            }
        },
    ]

    similar_users = []
    cursor = db["user_profiles"].aggregate(vector_pipeline)
    async for doc in cursor:
        similar_users.append(_serialize_doc(doc))
    elapsed = (time.monotonic() - t0) * 1000

    # Log query for visualization (without the actual vector)
    display_pipeline = [
        {
            "$vectorSearch": {
                "index": "fraud_similarity_index",
                "path": "fraud.embedding",
                "queryVector": f"<{len(query_embedding)}-dim embedding of: '{search_text[:80]}'>",
                "numCandidates": 50,
                "limit": 6,
                "filter": {"fraud.riskLevel": {"$ne": "low"}},
            }
        },
        vector_pipeline[1],
        vector_pipeline[2],
        vector_pipeline[3],
    ]

    queries.append({
        "agent": "similar_cases",
        "collection": "user_profiles",
        "operation": "aggregate",
        "pipeline": display_pipeline,
        "execution_time_ms": round(elapsed, 1),
        "docs_returned": len(similar_users),
        "mongodb_features": ["Atlas Vector Search", "Semantic Similarity", "Pre-filtering"],
    })

    # ── Prepare context for Claude ───────────────────────────────────
    context = f"""Target user: {user_id}
Identified fraud pattern: {fraud_pattern}
Confidence: {fraud_analysis.get('confidence', 0)}

Similar fraud profiles found via Atlas Vector Search:
{json.dumps(similar_users, indent=2, default=str)}
"""

    # ── Call Claude for similar-cases analysis ────────────────────────
    llm = ChatAnthropic(
        model="claude-sonnet-4-20250514",
        api_key=settings.anthropic_api_key,
        max_tokens=1024,
        temperature=0,
    )
    response = await llm.ainvoke([
        SystemMessage(content=SIMILAR_CASES_SYSTEM_PROMPT),
        HumanMessage(content=context),
    ])

    try:
        similar_cases = json.loads(response.content)
    except json.JSONDecodeError:
        text = response.content
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            similar_cases = json.loads(text[start:end])
        else:
            similar_cases = {
                "similar_profiles": [],
                "ring_analysis": {"likely_ring": False, "estimated_ring_size": 0, "shared_indicators": [], "confidence": 0.0},
                "pattern_frequency": {"occurrences_last_30_days": 0, "trend": "stable", "common_signals": []},
                "typical_resolution": {"most_common_action": "enhanced_monitoring", "avg_investigation_days": 5.0, "false_positive_rate": 0.3},
            }

    return {"similar_cases": similar_cases, "queries_executed": queries}
