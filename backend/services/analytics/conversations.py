"""
Conversation persistence, metadata generation, history retrieval,
demo users, and terminology data.
"""

import asyncio
import json
import re
import uuid
import logging
from datetime import datetime, timezone

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage

from backend.config import settings
from backend.database import get_screening_db
from backend.services.analytics.memory import VoyageEmbeddings, get_checkpointer

logger = logging.getLogger(__name__)


# ─── Conversation Persistence ─────────────────────────────────────

async def save_conversation_turn(
    session_id: str, user_id: str, question: str, answer: str,
    mql: str | None, latency_ms: float
):
    """Save/update a conversation document in chat_conversations for search indexing."""
    try:
        db = get_screening_db()
        coll = db["chat_conversations"]
        now = datetime.now(timezone.utc)

        message_pair = {
            "id": str(uuid.uuid4()),
            "question": question,
            "content": answer,
            "mql": mql or "",
            "latency_ms": latency_ms,
            "timestamp": now.isoformat(),
        }

        existing = await coll.find_one({"threadId": session_id})

        if existing is None:
            doc = {
                "threadId": session_id,
                "userId": user_id,
                "messages": [message_pair],
                "turnCount": 1,
                "lastQuestion": question,
                "createdAt": now,
                "updatedAt": now,
                "title": "",
                "summary": "",
                "category": "",
                "topics": [],
                "entities": [],
                "queryTypes": [],
                "complexity": "",
                "intent": "",
                "collections": [],
            }
            await coll.insert_one(doc)
            asyncio.create_task(_generate_conversation_metadata(session_id))
        else:
            turn_count = existing.get("turnCount", 0) + 1
            await coll.update_one(
                {"threadId": session_id},
                {
                    "$push": {"messages": message_pair},
                    "$set": {
                        "turnCount": turn_count,
                        "lastQuestion": question,
                        "updatedAt": now,
                    },
                },
            )
            if turn_count % 3 == 0:
                asyncio.create_task(_generate_conversation_metadata(session_id))

    except Exception as e:
        logger.error("Failed to save conversation turn: %s", e)


async def _generate_conversation_metadata(session_id: str):
    """Use a cheap LLM call to classify a conversation for faceted search."""
    try:
        db = get_screening_db()
        coll = db["chat_conversations"]
        doc = await coll.find_one({"threadId": session_id})
        if not doc:
            return

        digest_parts = []
        for msg in doc.get("messages", [])[:20]:
            digest_parts.append(f"Q: {msg['question']}")
            ans = msg.get("content", "")[:500]
            digest_parts.append(f"A: {ans}")
        digest = "\n".join(digest_parts)

        model = ChatBedrockConverse(
            model="apac.anthropic.claude-3-haiku-20240307-v1:0",
            region_name=settings.bedrock_region,
            max_tokens=500,
        )

        classification_prompt = f"""Classify this analytics chatbot conversation. Return ONLY valid JSON with these fields:
- title: short descriptive title (max 60 chars)
- summary: 1-2 sentence summary
- category: one of [user-metrics, kyc-compliance, wallet-financial, card-payment, activity-engagement, cross-domain, system]
- topics: array of 1-4 topic tags (e.g. ["MAU", "churn", "wallet-balance"])
- entities: array of referenced entities (collection names, field names mentioned)
- queryTypes: array from [count, aggregation, lookup, trend, comparison, distribution]
- complexity: one of [simple, moderate, complex]
- intent: one of [exploration, reporting, investigation, monitoring]
- collections: array of MongoDB collections queried (e.g. ["user_profiles"])

Conversation:
{digest}

JSON:"""

        response = await model.ainvoke([HumanMessage(content=classification_prompt)])
        raw = response.content.strip()
        json_match = re.search(r"\{[\s\S]*\}", raw)
        if not json_match:
            logger.warning("Metadata generation returned no JSON for %s", session_id)
            return

        metadata = json.loads(json_match.group())

        update_fields = {
            "title": metadata.get("title", ""),
            "summary": metadata.get("summary", ""),
            "category": metadata.get("category", ""),
            "topics": metadata.get("topics", []),
            "entities": metadata.get("entities", []),
            "queryTypes": metadata.get("queryTypes", []),
            "complexity": metadata.get("complexity", ""),
            "intent": metadata.get("intent", ""),
            "collections": metadata.get("collections", []),
        }

        try:
            embed_text = f"{metadata.get('title', '')} {metadata.get('summary', '')} {digest}"
            embedder = VoyageEmbeddings(
                model=settings.voyage_model,
                api_key=settings.voyage_api_key,
                dimensions=settings.voyage_dimensions,
            )
            update_fields["searchEmbedding"] = embedder.embed_query(embed_text)
            logger.info("Generated search embedding for conversation %s", session_id)
        except Exception as embed_err:
            logger.warning("Failed to generate search embedding for %s: %s", session_id, embed_err)

        await coll.update_one({"threadId": session_id}, {"$set": update_fields})
        logger.info("Generated metadata for conversation %s: %s", session_id, metadata.get("title", ""))

    except Exception as e:
        logger.error("Failed to generate conversation metadata: %s", e, exc_info=True)


# ─── History & Retrieval ──────────────────────────────────────────

async def get_history(session_id: str) -> list[dict]:
    """Read conversation history from the chat_conversations collection."""
    db = get_screening_db()
    doc = await db["chat_conversations"].find_one({"threadId": session_id})
    if not doc:
        return []
    return doc.get("messages", [])


async def get_conversation(thread_id: str) -> dict | None:
    """Get full conversation document."""
    db = get_screening_db()
    doc = await db["chat_conversations"].find_one({"threadId": thread_id})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


async def resume_conversation(thread_id: str) -> dict | None:
    """Return conversation + verify checkpoint exists for resume."""
    conversation = await get_conversation(thread_id)
    if not conversation:
        return None

    checkpointer = get_checkpointer()
    if checkpointer:
        config = {"configurable": {"thread_id": thread_id}}
        try:
            checkpoint_tuple = await checkpointer.aget_tuple(config)
            conversation["hasCheckpoint"] = checkpoint_tuple is not None
        except Exception:
            conversation["hasCheckpoint"] = False
    else:
        conversation["hasCheckpoint"] = False

    return conversation


# ─── Demo Users (UI-only: populates the user-switcher dropdown in the frontend) ──

DEMO_USERS = [
    {
        "userId": "analyst-1",
        "name": "Sarah Chen",
        "role": "Chief Compliance Officer",
        "avatar": "SC",
        "department": "Risk & Compliance",
    },
    {
        "userId": "analyst-2",
        "name": "Amir Hassan",
        "role": "Growth Product Manager",
        "avatar": "AH",
        "department": "Product & Growth",
    },
]


async def seed_app_users():
    """Upsert demo users into app_users collection on startup.

    UI-only: seeds the personas shown in the frontend user-switcher.
    """
    db = get_screening_db()
    coll = db["app_users"]
    for user in DEMO_USERS:
        await coll.update_one(
            {"userId": user["userId"]},
            {"$set": user},
            upsert=True,
        )
    logger.info("Seeded %d demo users into app_users", len(DEMO_USERS))


async def get_users() -> list[dict]:
    """Return all app users."""
    db = get_screening_db()
    users = []
    async for doc in db["app_users"].find({}, {"_id": 0}):
        users.append(doc)
    return users


# ─── Terminology (UI-only: displayed in the frontend help/glossary panel) ──

TERMINOLOGY = [
    {"term": "MAU", "aliases": ["monthly active users"], "meaning": "Users with at least 1 transaction in last 30 days", "field": "activitySummary.lastTransactionAt"},
    {"term": "new users", "aliases": [], "meaning": "Users created in the specified period", "field": "createdAt"},
    {"term": "active users", "aliases": [], "meaning": "Users with status 'active'", "field": "status"},
    {"term": "verified users", "aliases": [], "meaning": "Users with KYC verified", "field": "kyc.status"},
    {"term": "premium users", "aliases": [], "meaning": "Users on premium wallet tier", "field": "wallet.tier"},
    {"term": "flagged users", "aliases": [], "meaning": "Users flagged by screening", "field": "screening.riskFlag"},
    {"term": "high-risk", "aliases": ["risky users"], "meaning": "Users with high KYC risk level", "field": "kyc.riskLevel"},
    {"term": "churn", "aliases": ["churned users"], "meaning": "Users active last month but not this month", "field": "activitySummary.lastTransactionAt"},
    {"term": "big spenders", "aliases": [], "meaning": "Users with high monthly average spend", "field": "activitySummary.monthlyAvgSpend"},
    {"term": "dormant", "aliases": [], "meaning": "Users with no transactions in 60+ days", "field": "activitySummary.lastTransactionAt"},
]


def get_terminology() -> list[dict]:
    return TERMINOLOGY
