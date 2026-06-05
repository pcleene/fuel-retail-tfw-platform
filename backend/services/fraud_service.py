"""
Fraud Detection Service — UC3
Dashboard reads, signal-rule management, embedding backfill, and similarity search.
Events are NOT ingested via HTTP — they flow through MSK → Atlas Stream Processing → MongoDB.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)


class FraudService:
    def __init__(self, db):
        self.db = db
        self.events = db["events"]
        self.alerts = db["fraud_alerts"]
        self.rules = db["signal_rules"]
        self.users = db["user_profiles"]

    # ── Dashboard stats ──────────────────────────────────────────────

    async def get_stats(self) -> dict:
        now = datetime.now(timezone.utc)
        one_hour_ago = now - timedelta(hours=1)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        total_events = await self.events.count_documents({})
        total_alerts = await self.alerts.count_documents({})
        flagged_users = await self.users.count_documents({"fraud.riskLevel": {"$ne": "low"}})
        events_last_hour = await self.events.count_documents({"timestamp": {"$gte": one_hour_ago}})
        alerts_today = await self.alerts.count_documents({"createdAt": {"$gte": today_start}})

        return {
            "totalEvents": total_events,
            "totalAlerts": total_alerts,
            "flaggedUsers": flagged_users,
            "eventsLastHour": events_last_hour,
            "alertsToday": alerts_today,
        }

    # ── Recent events feed ───────────────────────────────────────────

    async def get_recent_events(self, limit: int = 50) -> list[dict]:
        cursor = self.events.find(
            {}, {"_id": 0}
        ).sort("timestamp", -1).limit(limit)
        results = []
        async for doc in cursor:
            if "timestamp" in doc and hasattr(doc["timestamp"], "isoformat"):
                doc["timestamp"] = doc["timestamp"].isoformat()
            if "_ingested_at" in doc and hasattr(doc["_ingested_at"], "isoformat"):
                doc["_ingested_at"] = doc["_ingested_at"].isoformat()
            results.append(doc)
        return results

    # ── Alerts ───────────────────────────────────────────────────────

    async def get_alerts(self, limit: int = 50) -> list[dict]:
        cursor = self.alerts.find({}, {"_id": 0}).sort("createdAt", -1).limit(limit)
        results = []
        async for doc in cursor:
            _serialize_dates(doc)
            results.append(doc)
        return results

    # ── Signal rules ─────────────────────────────────────────────────

    async def get_signal_rules(self) -> list[dict]:
        cursor = self.rules.find({}, {"_id": 0}).sort("key", 1)
        return await cursor.to_list(100)

    async def update_signal_rule(self, key: str, updates: dict[str, Any]) -> dict:
        """Update a signal rule's threshold values in variants.Enabled.value."""
        update_fields: dict[str, Any] = {}
        for field, value in updates.items():
            update_fields[f"variants.Enabled.value.{field}"] = value
        update_fields["updatedAt"] = int(datetime.now(timezone.utc).timestamp())

        await self.rules.update_one(
            {"key": key},
            {"$set": update_fields, "$inc": {"version": 1}},
        )
        updated = await self.rules.find_one({"key": key}, {"_id": 0})
        return updated or {"error": "Rule not found"}

    # ── Flagged users ────────────────────────────────────────────────

    async def get_flagged_users(self) -> list[dict]:
        cursor = self.users.find(
            {"fraud.riskLevel": {"$ne": "low"}},
            {
                "_id": 0,
                "userId": 1, "fullName": 1, "status": 1,
                "kyc": 1, "wallet": 1, "linkedCards": 1,
                "activitySummary": 1, "screening": 1, "fraud": 1,
            },
        ).sort("fraud.lastAlertAt", -1).limit(50)
        results = []
        async for doc in cursor:
            _serialize_dates_recursive(doc)
            results.append(doc)
        return results

    # ── Fraud similarity (Voyage AI + Atlas Vector Search) ───────────

    async def find_similar_users(self, user_id: str, top_k: int = 10) -> list[dict]:
        """Find users with similar fraud profiles via Atlas Vector Search."""
        user = await self.users.find_one(
            {"userId": user_id},
            {"fraud.embedding": 1, "userId": 1},
        )
        if not user or not user.get("fraud", {}).get("embedding"):
            return []

        pipeline = [
            {
                "$vectorSearch": {
                    "index": "fraud_similarity_index",
                    "path": "fraud.embedding",
                    "queryVector": user["fraud"]["embedding"],
                    "numCandidates": top_k * 10,
                    "limit": top_k + 1,
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
        cursor = self.users.aggregate(pipeline)
        results = []
        async for doc in cursor:
            _serialize_dates_recursive(doc)
            results.append(doc)
        return results[:top_k]

    async def backfill_embeddings(self) -> dict:
        """Generate Voyage AI embeddings for flagged users missing them."""
        cursor = self.users.find(
            {"fraud.riskLevel": {"$ne": "low"}, "fraud.embedding": None},
            {"userId": 1, "fraud": 1, "activitySummary": 1, "wallet": 1, "kyc": 1, "linkedCards": 1},
        )
        count = 0
        async for user in cursor:
            text = compose_fraud_profile_text(user)
            embedding = await generate_fraud_embedding(text)
            if embedding:
                await self.users.update_one(
                    {"userId": user["userId"]},
                    {"$set": {"fraud.embedding": embedding}},
                )
                count += 1
        return {"usersUpdated": count}

    # ── Pipeline definitions (educational) ───────────────────────────

    def get_pipeline_definitions(self) -> list[dict]:
        return PIPELINE_DEFINITIONS


# ── Voyage AI helpers ────────────────────────────────────────────────

def compose_fraud_profile_text(user: dict) -> str:
    """Compose a text representation of a user's fraud profile for embedding."""
    parts = []

    for alert in user.get("fraud", {}).get("alerts", []):
        parts.append(f"Signal {alert['signal']}: {alert['details']}. Severity: {alert['severity']}.")
        for evt in alert.get("events", []):
            props = evt.get("properties", {})
            parts.append(
                f"Event: {evt['name']}, amount: {props.get('amount', 'N/A')}, "
                f"recipient: {props.get('recipient', 'N/A')}"
            )

    activity = user.get("activitySummary", {})
    wallet = user.get("wallet", {})
    kyc = user.get("kyc", {})
    cards = user.get("linkedCards", [])

    parts.append(f"Wallet tier: {wallet.get('tier', 'unknown')}, balance: {wallet.get('balance', 0)} MYR")
    parts.append(f"KYC status: {kyc.get('status', 'unknown')}, risk level: {kyc.get('riskLevel', 'unknown')}")
    parts.append(
        f"Total transactions: {activity.get('totalTransactions', 0)}, "
        f"total spend: {activity.get('totalSpend', 0)} MYR, "
        f"monthly avg: {activity.get('monthlyAvgSpend', 0)} MYR"
    )
    parts.append(f"Linked cards: {len(cards)}")

    signals = user.get("fraud", {}).get("signalsSeen", [])
    if signals:
        parts.append(f"Signals triggered: {', '.join(signals)}")

    return " | ".join(parts)


async def generate_fraud_embedding(text: str) -> list[float] | None:
    """Call Voyage AI to generate embedding for fraud profile text."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.voyageai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {settings.voyage_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.voyage_model,
                    "input": [text],
                    "input_type": "document",
                },
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()["data"][0]["embedding"]
    except Exception as e:
        logger.error("Voyage AI embedding failed: %s", e)
        return None


# ── Date serialization helpers ───────────────────────────────────────

def _serialize_dates(doc: dict):
    for key, val in doc.items():
        if hasattr(val, "isoformat"):
            doc[key] = val.isoformat()
        elif isinstance(val, dict):
            _serialize_dates(val)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    _serialize_dates(item)


def _serialize_dates_recursive(doc: dict):
    _serialize_dates(doc)


# ── Pipeline definitions (for educational display) ───────────────────

PIPELINE_DEFINITIONS = [
    {
        "name": "FuelRetail-event-ingest",
        "description": "Passthrough — all events from MSK into events collection (dashboard feed)",
        "pipeline": [
            {"$source": {"connectionName": "UtilitymskKafkaConnection", "topic": "FuelRetail-fraud-events"}},
            {"$addFields": {"_ingested_at": "$$NOW", "_source_topic": "FuelRetail-fraud-events"}},
            {"$merge": {"into": {"connectionName": "EnergyOperator_cluster", "db": "FuelRetail_fraud", "coll": "events"}}},
        ],
    },
    {
        "name": "FuelRetail-signal-s01-topup-cluster",
        "description": "S01 Stage 1: Detects 2+ auto top-ups >= RM500 in 15min → writes state to user_profiles.fraud.signals.s01",
        "pipeline": [
            {"$source": {"connectionName": "UtilitymskKafkaConnection", "topic": "FuelRetail-fraud-events"}},
            {"$match": {"name": "auto_topup", "properties.amount": {"$gte": 500}}},
            {
                "$tumblingWindow": {
                    "interval": {"size": 15, "unit": "minute"},
                    "pipeline": [
                        {
                            "$group": {
                                "_id": "$user_id",
                                "topupCount": {"$sum": 1},
                                "firstTopupAt": {"$min": "$timestamp"},
                                "lastTopupAt": {"$max": "$timestamp"},
                                "recentHighTopups": {
                                    "$push": {
                                        "eventId": "$eventId",
                                        "amount": "$properties.amount",
                                        "timestamp": "$timestamp",
                                        "source": "$properties.source",
                                    }
                                },
                            }
                        },
                        {"$match": {"topupCount": {"$gte": 2}}},
                        {
                            "$addFields": {
                                "intervalSeconds": {
                                    "$dateDiff": {
                                        "startDate": "$firstTopupAt",
                                        "endDate": "$lastTopupAt",
                                        "unit": "second",
                                    }
                                }
                            }
                        },
                    ],
                }
            },
            {
                "$project": {
                    "userId": "$_id",
                    "fraud.signals.s01.topupClusterDetected": {"$literal": True},
                    "fraud.signals.s01.lastClusterAt": "$lastTopupAt",
                    "fraud.signals.s01.topupCount": "$topupCount",
                    "fraud.signals.s01.intervalSeconds": "$intervalSeconds",
                    "fraud.signals.s01.recentHighTopups": "$recentHighTopups",
                }
            },
            {
                "$merge": {
                    "into": {"connectionName": "EnergyOperator_cluster", "db": "FuelRetail_fraud", "coll": "user_profiles"},
                    "on": "userId",
                    "whenMatched": "merge",
                }
            },
        ],
    },
    {
        "name": "FuelRetail-signal-s01-transfer-check",
        "description": "S01 Stage 2: Windowless — on each InstantTransfer_transfer_out, $lookup user profile, check if flagged + within 30min → alert",
        "pipeline": [
            {"$source": {"connectionName": "UtilitymskKafkaConnection", "topic": "FuelRetail-fraud-events"}},
            {"$match": {"name": "InstantTransfer_transfer_out"}},
            {
                "$lookup": {
                    "connectionName": "EnergyOperator_cluster",
                    "from": {"db": "FuelRetail_fraud", "coll": "user_profiles"},
                    "localField": "user_id",
                    "foreignField": "userId",
                    "as": "userProfile",
                }
            },
            {"$unwind": "$userProfile"},
            {
                "$match": {
                    "userProfile.fraud.signals.s01.topupClusterDetected": True,
                    "$expr": {
                        "$lte": [
                            {"$dateDiff": {
                                "startDate": "$userProfile.fraud.signals.s01.lastClusterAt",
                                "endDate": "$timestamp",
                                "unit": "minute",
                            }},
                            30,
                        ]
                    },
                }
            },
            {
                "$addFields": {
                    "alertId": {"$concat": ["alert-s01-", {"$toString": "$user_id"}, "-", {"$toString": "$$NOW"}]},
                    "userId": "$user_id",
                    "signal": "S01",
                    "severity": "critical",
                    "status": "open",
                    "details": "Auto top-up >= RM500 x 2+ within 15min + InstantTransfer transfer out within 30min",
                    "ruleSnapshot": {
                        "topupAmountThreshold": 500,
                        "topupCountThreshold": 2,
                        "topupWindowMinutes": 15,
                        "transferWindowMinutes": 30,
                    },
                    "events": {
                        "$concatArrays": [
                            "$userProfile.fraud.signals.s01.recentHighTopups",
                            [{"eventId": "$eventId", "name": "$name", "amount": "$properties.amount",
                              "timestamp": "$timestamp", "properties": "$properties"}],
                        ]
                    },
                    "createdAt": "$$NOW",
                }
            },
            {
                "$project": {
                    "alertId": 1, "userId": 1, "signal": 1, "severity": 1, "status": 1,
                    "details": 1, "ruleSnapshot": 1, "events": 1, "createdAt": 1,
                }
            },
            {"$merge": {"into": {"connectionName": "EnergyOperator_cluster", "db": "FuelRetail_fraud", "coll": "fraud_alerts"}}},
        ],
    },
    {
        "name": "FuelRetail-topup-state-writer",
        "description": "Windowless — updates user_profiles.fraud.lastTopupAt on every top-up event (needed by S02/S03 lookups)",
        "pipeline": [
            {"$source": {"connectionName": "UtilitymskKafkaConnection", "topic": "FuelRetail-fraud-events"}},
            {"$match": {"name": {"$in": ["auto_topup", "manual_topup"]}}},
            {
                "$addFields": {
                    "userId": "$user_id",
                    "fraud.lastTopupAt": "$timestamp",
                    "fraud.lastTopupAmount": "$properties.amount",
                    "fraud.lastTopupType": "$name",
                }
            },
            {"$project": {"userId": 1, "fraud": 1}},
            {
                "$merge": {
                    "into": {"connectionName": "EnergyOperator_cluster", "db": "FuelRetail_fraud", "coll": "user_profiles"},
                    "on": "userId",
                    "whenMatched": "merge",
                }
            },
        ],
    },
    {
        "name": "FuelRetail-signal-s02",
        "description": "S02: Windowless — each InstantTransfer payment > RM500 (non-ewallet) does $lookup to check if lastTopupAt within 30min",
        "pipeline": [
            {"$source": {"connectionName": "UtilitymskKafkaConnection", "topic": "FuelRetail-fraud-events"}},
            {"$match": {"name": "InstantTransfer_payment", "properties.amount": {"$gt": 500}, "properties.type": {"$ne": "ewallet"}}},
            {
                "$lookup": {
                    "connectionName": "EnergyOperator_cluster",
                    "from": {"db": "FuelRetail_fraud", "coll": "user_profiles"},
                    "localField": "user_id",
                    "foreignField": "userId",
                    "as": "userProfile",
                }
            },
            {"$unwind": "$userProfile"},
            {
                "$match": {
                    "userProfile.fraud.lastTopupAt": {"$exists": True},
                    "$expr": {
                        "$lte": [
                            {"$dateDiff": {
                                "startDate": "$userProfile.fraud.lastTopupAt",
                                "endDate": "$timestamp",
                                "unit": "minute",
                            }},
                            30,
                        ]
                    },
                }
            },
            {
                "$addFields": {
                    "alertId": {"$concat": ["alert-s02-", {"$toString": "$user_id"}, "-", {"$toString": "$$NOW"}]},
                    "userId": "$user_id",
                    "signal": "S02", "severity": "high", "status": "open",
                    "details": "InstantTransfer payment > RM500 (non-ewallet) within 30min after top-up",
                    "ruleSnapshot": {"amountThreshold": 500, "windowMinutes": 30},
                    "events": [{"eventId": "$eventId", "name": "$name", "amount": "$properties.amount",
                                "timestamp": "$timestamp", "properties": "$properties"}],
                    "topupInfo": {
                        "lastTopupAt": "$userProfile.fraud.lastTopupAt",
                        "lastTopupAmount": "$userProfile.fraud.lastTopupAmount",
                        "lastTopupType": "$userProfile.fraud.lastTopupType",
                    },
                    "createdAt": "$$NOW",
                }
            },
            {
                "$project": {
                    "alertId": 1, "userId": 1, "signal": 1, "severity": 1, "status": 1,
                    "details": 1, "ruleSnapshot": 1, "events": 1, "topupInfo": 1, "createdAt": 1,
                }
            },
            {"$merge": {"into": {"connectionName": "EnergyOperator_cluster", "db": "FuelRetail_fraud", "coll": "fraud_alerts"}}},
        ],
    },
    {
        "name": "FuelRetail-signal-s03",
        "description": "S03: Hybrid — 30min window counts fund_out_transfer > RM500, at close $lookup user profile to check recent top-up",
        "pipeline": [
            {"$source": {"connectionName": "UtilitymskKafkaConnection", "topic": "FuelRetail-fraud-events"}},
            {"$match": {"name": "fund_out_transfer", "properties.amount": {"$gt": 500}}},
            {
                "$tumblingWindow": {
                    "interval": {"size": 30, "unit": "minute"},
                    "pipeline": [
                        {
                            "$group": {
                                "_id": "$user_id",
                                "fundOutCount": {"$sum": 1},
                                "totalAmount": {"$sum": "$properties.amount"},
                                "fundOuts": {
                                    "$push": {
                                        "eventId": "$eventId", "name": "$name",
                                        "amount": "$properties.amount", "timestamp": "$timestamp",
                                        "properties": "$properties",
                                    }
                                },
                            }
                        },
                        {"$match": {"fundOutCount": {"$gte": 2}}},
                    ],
                }
            },
            {
                "$lookup": {
                    "connectionName": "EnergyOperator_cluster",
                    "from": {"db": "FuelRetail_fraud", "coll": "user_profiles"},
                    "localField": "_id",
                    "foreignField": "userId",
                    "as": "userProfile",
                }
            },
            {"$unwind": "$userProfile"},
            {
                "$match": {
                    "userProfile.fraud.lastTopupAt": {"$exists": True},
                    "$expr": {
                        "$lte": [
                            {"$dateDiff": {
                                "startDate": "$userProfile.fraud.lastTopupAt",
                                "endDate": "$$NOW",
                                "unit": "minute",
                            }},
                            60,
                        ]
                    },
                }
            },
            {
                "$addFields": {
                    "alertId": {"$concat": ["alert-s03-", {"$toString": "$_id"}, "-", {"$toString": "$$NOW"}]},
                    "userId": "$_id",
                    "signal": "S03", "severity": "high", "status": "open",
                    "details": {"$concat": [
                        {"$toString": "$fundOutCount"}, " fund-out transfers totalling RM",
                        {"$toString": {"$round": ["$totalAmount", 2]}}, " within 30min after top-up",
                    ]},
                    "events": "$fundOuts",
                    "ruleSnapshot": {"amountThreshold": 500, "countThreshold": 2, "windowMinutes": 30},
                    "topupInfo": {
                        "lastTopupAt": "$userProfile.fraud.lastTopupAt",
                        "lastTopupAmount": "$userProfile.fraud.lastTopupAmount",
                        "lastTopupType": "$userProfile.fraud.lastTopupType",
                    },
                    "createdAt": "$$NOW",
                }
            },
            {
                "$project": {
                    "alertId": 1, "userId": 1, "signal": 1, "severity": 1, "status": 1,
                    "details": 1, "ruleSnapshot": 1, "events": 1, "topupInfo": 1, "createdAt": 1,
                }
            },
            {"$merge": {"into": {"connectionName": "EnergyOperator_cluster", "db": "FuelRetail_fraud", "coll": "fraud_alerts"}}},
        ],
    },
    {
        "name": "FuelRetail-signal-s04",
        "description": "S04: 3+ cards linked within 1 hour — single pipeline",
        "pipeline": [
            {"$source": {"connectionName": "UtilitymskKafkaConnection", "topic": "FuelRetail-fraud-events"}},
            {"$match": {"name": "card_linked"}},
            {
                "$tumblingWindow": {
                    "interval": {"size": 60, "unit": "minute"},
                    "pipeline": [
                        {
                            "$group": {
                                "_id": "$user_id",
                                "cardCount": {"$sum": 1},
                                "cards": {
                                    "$push": {"eventId": "$eventId", "name": "$name",
                                              "ts": "$timestamp", "properties": "$properties"}
                                },
                            }
                        },
                        {"$match": {"cardCount": {"$gte": 3}}},
                    ],
                }
            },
            {
                "$addFields": {
                    "alertId": {"$concat": ["alert-s04-", {"$toString": "$$NOW"}]},
                    "userId": "$_id",
                    "signal": "S04", "severity": "medium", "status": "open",
                    "details": "3+ cards linked within 1 hour",
                    "events": "$cards",
                    "ruleSnapshot": {"cardCountThreshold": 3, "velocityWindowMinutes": 60},
                    "createdAt": "$$NOW",
                }
            },
            {"$merge": {"into": {"connectionName": "EnergyOperator_cluster", "db": "FuelRetail_fraud", "coll": "fraud_alerts"}}},
        ],
    },
]
