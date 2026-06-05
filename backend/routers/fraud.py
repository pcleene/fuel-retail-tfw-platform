"""UC3 Fraud Detection router — dashboard + rules + simulator control + agent investigation.

Events are NOT ingested via HTTP. They flow through MSK → Atlas Stream Processing → MongoDB.
This router provides the dashboard UI with reads, manages signal rules, and triggers
LangGraph-based fraud investigations.
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException

from backend.database import get_fraud_db
from backend.services.fraud_service import FraudService
from backend.models.fraud import SimulateRequest, SignalRuleUpdate
from backend.kafka.simulator import simulate_scenario

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/fraud", tags=["fraud"])


def _svc():
    return FraudService(get_fraud_db())


# ── Simulator (produces events to MSK) ──────────────────────────────

@router.post("/simulate")
async def simulate(req: SimulateRequest):
    """Trigger Kafka producer to generate a scenario's events to MSK."""
    return await simulate_scenario(req.scenario, req.user_id)


# ── Dashboard reads ──────────────────────────────────────────────────

@router.get("/alerts")
async def get_alerts(limit: int = 50):
    svc = _svc()
    return await svc.get_alerts(limit)


@router.get("/events/recent")
async def get_recent_events(limit: int = 50):
    svc = _svc()
    return await svc.get_recent_events(limit)


@router.get("/stats")
async def get_stats():
    svc = _svc()
    return await svc.get_stats()


# ── Signal rules ─────────────────────────────────────────────────────

@router.get("/signal-rules")
async def get_signal_rules():
    svc = _svc()
    return await svc.get_signal_rules()


@router.put("/signal-rules/{key}")
async def update_signal_rule(key: str, body: SignalRuleUpdate):
    svc = _svc()
    return await svc.update_signal_rule(key, body.updates)


# ── Flagged users ────────────────────────────────────────────────────

@router.get("/users/flagged")
async def get_flagged_users():
    svc = _svc()
    return await svc.get_flagged_users()


# ── Fraud similarity (Atlas Vector Search) ───────────────────────────

@router.get("/users/{user_id}/similar")
async def find_similar_users(user_id: str, top_k: int = 10):
    svc = _svc()
    return await svc.find_similar_users(user_id, top_k)


@router.post("/users/backfill-embeddings")
async def backfill_embeddings():
    svc = _svc()
    return await svc.backfill_embeddings()


# ── Pipeline definitions (educational) ───────────────────────────────

@router.get("/pipeline-definitions")
async def get_pipeline_definitions():
    svc = _svc()
    return svc.get_pipeline_definitions()


# ── LangGraph fraud investigation agent ──────────────────────────────

@router.post("/investigate/{user_id}")
async def investigate_user(user_id: str):
    """Trigger the LangGraph fraud investigation agent for a specific user.

    Investigation runs in background. Progress and results are pushed via SSE.
    """
    try:
        from backend.services.change_stream_watcher import get_watcher
        watcher = get_watcher()

        if not watcher._should_investigate(user_id):
            return {
                "status": "skipped",
                "reason": "Investigation already in progress or recently completed for this user",
                "userId": user_id,
            }

        asyncio.create_task(watcher.run_investigation(user_id, alert_id=None))

        return {
            "status": "started",
            "userId": user_id,
            "message": "Investigation started. Results will be pushed via SSE.",
        }
    except Exception as e:
        logger.exception("Investigation trigger failed for user %s", user_id)
        raise HTTPException(status_code=500, detail=f"Investigation trigger failed: {str(e)}")


@router.get("/investigations")
async def get_investigations(limit: int = 20):
    """Get recent fraud investigations."""
    db = get_fraud_db()
    cursor = db["fraud_investigations"].find(
        {}, {"_id": 0}
    ).sort("createdAt", -1).limit(limit)
    results = []
    async for doc in cursor:
        for key, val in doc.items():
            if hasattr(val, "isoformat"):
                doc[key] = val.isoformat()
        results.append(doc)
    return results


@router.get("/investigations/{user_id}")
async def get_user_investigations(user_id: str, limit: int = 5):
    """Get investigations for a specific user."""
    db = get_fraud_db()
    cursor = db["fraud_investigations"].find(
        {"userId": user_id}, {"_id": 0}
    ).sort("createdAt", -1).limit(limit)
    results = []
    async for doc in cursor:
        for key, val in doc.items():
            if hasattr(val, "isoformat"):
                doc[key] = val.isoformat()
        results.append(doc)
    return results
