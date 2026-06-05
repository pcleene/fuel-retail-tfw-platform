"""Event simulator — generates realistic fraud scenarios via EC2 → MSK.

Primary mode: SSH to EC2 and produce events to MSK (real pipeline).
Events flow: EC2 → MSK → Atlas Stream Processing → MongoDB → Change Stream → Agent.

Fallback: Insert events + alerts directly into MongoDB (local dev).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from backend.config import settings

logger = logging.getLogger(__name__)

# EC2 connection details
EC2_HOST = "203.0.113.11"
EC2_USER = "ubuntu"
EC2_KEY = "<local-path>"
MSK_BROKERS = settings.kafka_bootstrap_servers
MSK_TOPIC = settings.kafka_topic


def _make_event(name: str, user_id: str, properties: dict,
                timestamp: datetime | None = None,
                metadata: dict | None = None) -> dict:
    """Build an event document."""
    ts = timestamp or datetime.now(timezone.utc)
    return {
        "eventId": f"evt-{uuid4().hex[:12]}",
        "origin": "FuelRetail-app",
        "name": name,
        "user_id": user_id,
        "timestamp": ts if isinstance(ts, str) else ts.isoformat(),
        "properties": properties,
        "metadata": metadata or {
            "device": "iPhone 15 Pro",
            "ip": f"203.0.113.{hash(user_id) % 254 + 1}",
            "sessionId": f"sess-{uuid4().hex[:12]}",
        },
    }


def _build_scenario_events(scenario: str, uid: str, now: datetime) -> list[dict]:
    """Build the list of events for a given scenario."""
    events = []

    if scenario == "signal_1":
        # S01: 2x auto top-up >= RM500 within 15 min + InstantTransfer transfer out within 30 min
        events.append(_make_event(
            "auto_topup", uid,
            {"amount": 600, "source": "card_ending_1234", "currency": "MYR"},
            timestamp=now - timedelta(seconds=40),
        ))
        events.append(_make_event(
            "auto_topup", uid,
            {"amount": 750, "source": "card_ending_1234", "currency": "MYR"},
            timestamp=now - timedelta(seconds=20),
        ))
        events.append(_make_event(
            "InstantTransfer_transfer_out", uid,
            {"amount": 1200, "recipient": "+60187654321", "currency": "MYR"},
            timestamp=now - timedelta(seconds=5),
        ))

    elif scenario == "signal_2":
        # S02: Top-up + InstantTransfer payment > RM500 (bank_transfer) within 30 min
        events.append(_make_event(
            "auto_topup", uid,
            {"amount": 500, "source": "card_ending_5678", "currency": "MYR"},
            timestamp=now - timedelta(seconds=30),
        ))
        events.append(_make_event(
            "InstantTransfer_payment", uid,
            {"amount": 800, "type": "bank_transfer", "merchant": "Unknown Merchant", "currency": "MYR"},
            timestamp=now - timedelta(seconds=5),
        ))

    elif scenario == "signal_3":
        # S03: Top-up + 2x fund-out > RM500 within 30 min
        events.append(_make_event(
            "manual_topup", uid,
            {"amount": 1000, "source": "bank_transfer", "currency": "MYR"},
            timestamp=now - timedelta(seconds=50),
        ))
        events.append(_make_event(
            "fund_out_transfer", uid,
            {"amount": 600, "recipient": "acc_001", "currency": "MYR"},
            timestamp=now - timedelta(seconds=20),
        ))
        events.append(_make_event(
            "fund_out_transfer", uid,
            {"amount": 700, "recipient": "acc_002", "currency": "MYR"},
            timestamp=now - timedelta(seconds=5),
        ))

    elif scenario == "signal_4":
        # S04: 3+ cards linked within 1 hour
        banks = ["RegionalBankB", "CIMB", "RHB"]
        for i in range(3):
            events.append(_make_event(
                "card_linked", uid,
                {"cardType": ["visa", "mastercard", "visa"][i], "last4": f"{1000 + i}", "bank": banks[i]},
                timestamp=now - timedelta(seconds=40 - i * 15),
            ))

    elif scenario == "clean":
        # Normal low-value transactions — should NOT trigger any signals
        events.append(_make_event(
            "fuel_purchase", uid,
            {"amount": 45.50, "merchant": "EnergyOperator Bangsar", "litres": 20.5, "currency": "MYR"},
            timestamp=now - timedelta(seconds=50),
        ))
        events.append(_make_event(
            "auto_topup", uid,
            {"amount": 50, "source": "card_ending_9999", "currency": "MYR"},
            timestamp=now - timedelta(seconds=30),
        ))
        events.append(_make_event(
            "InstantTransfer_payment", uid,
            {"amount": 25, "type": "ewallet", "merchant": "Grab", "currency": "MYR"},
            timestamp=now - timedelta(seconds=10),
        ))

    return events


# Signal → alert metadata mapping (for local fallback only)
SIGNAL_META = {
    "signal_1": {
        "signal": "S01", "severity": "critical",
        "details": "Top-up cluster detected: 2 auto top-ups >= RM500 within 15 min, followed by InstantTransfer transfer out within 30 min.",
        "ruleSnapshot": {"topupAmountThreshold": 500, "topupCountThreshold": 2, "topupWindowMinutes": 15, "transferWindowMinutes": 30},
    },
    "signal_2": {
        "signal": "S02", "severity": "high",
        "details": "High-value InstantTransfer payment (RM800, bank_transfer) detected within 30 min after top-up.",
        "ruleSnapshot": {"amountThreshold": 500, "windowMinutes": 30},
    },
    "signal_3": {
        "signal": "S03", "severity": "high",
        "details": "Multiple fund-out transfers (2x > RM500) detected within 30 min after manual top-up.",
        "ruleSnapshot": {"amountThreshold": 500, "countThreshold": 2, "windowMinutes": 30},
    },
    "signal_4": {
        "signal": "S04", "severity": "medium",
        "details": "Rapid card linking detected: 3 cards linked within 60 min.",
        "ruleSnapshot": {"cardCountThreshold": 3, "velocityWindowMinutes": 60},
    },
}


def _build_ec2_producer_script(events: list[dict], topic: str, brokers: str) -> str:
    """Build a self-contained Python script to run on EC2 for producing events to MSK.

    Uses base64-encoded JSON to avoid shell/quote escaping issues.
    """
    events_b64 = base64.b64encode(json.dumps(events, default=str).encode()).decode()
    return f'''import asyncio, json, ssl, base64
from aiokafka import AIOKafkaProducer
from aiokafka.abc import AbstractTokenProvider
from aws_msk_iam_sasl_signer import MSKAuthTokenProvider

class TokenProvider(AbstractTokenProvider):
    async def token(self):
        token, _ = MSKAuthTokenProvider.generate_auth_token("ap-southeast-1")
        return token

async def main():
    events = json.loads(base64.b64decode("{events_b64}").decode())
    producer = AIOKafkaProducer(
        bootstrap_servers="{brokers}",
        security_protocol="SASL_SSL",
        sasl_mechanism="OAUTHBEARER",
        sasl_oauth_token_provider=TokenProvider(),
        ssl_context=ssl.create_default_context(),
        value_serializer=lambda v: json.dumps(v, default=str).encode(),
        key_serializer=lambda k: k.encode() if k else None,
    )
    await producer.start()
    try:
        for evt in events:
            await producer.send("{topic}", value=evt, key=evt["user_id"])
            print(f"Produced: {{evt['name']}} for {{evt['user_id']}}")
        await producer.flush()
        print(f"Done: {{len(events)}} events produced to {topic}")
    finally:
        await producer.stop()

asyncio.run(main())
'''


async def _simulate_ec2(scenario: str, uid: str, now: datetime) -> dict:
    """EC2 simulation mode — SSH to EC2 and produce events to MSK via stdin pipe."""
    events = _build_scenario_events(scenario, uid, now)
    if not events:
        return {"error": f"Unknown scenario: {scenario}"}

    script = _build_ec2_producer_script(events, MSK_TOPIC, MSK_BROKERS)

    # Pipe the script via stdin to avoid shell escaping issues
    cmd = [
        "ssh",
        "-i", EC2_KEY,
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        f"{EC2_USER}@{EC2_HOST}",
        "python3", "-",
    ]

    logger.info("SSHing to EC2 to produce %d events for %s (scenario: %s)", len(events), uid, scenario)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(input=script.encode()), timeout=60
    )

    stdout_str = stdout.decode().strip()
    stderr_str = stderr.decode().strip()

    if proc.returncode != 0:
        logger.error("EC2 producer failed (exit %d): %s", proc.returncode, stderr_str)
        raise RuntimeError(f"EC2 producer failed: {stderr_str}")

    logger.info("EC2 producer output: %s", stdout_str)

    return {
        "scenario": scenario,
        "userId": uid,
        "eventsProduced": len(events),
        "events": events,
        "mode": "ec2",
        "ec2Output": stdout_str,
    }


async def _simulate_local(scenario: str, uid: str, now: datetime) -> dict:
    """Local fallback — inserts events + alert directly into MongoDB."""
    from backend.database import get_fraud_db
    db = get_fraud_db()

    events = _build_scenario_events(scenario, uid, now)
    if not events:
        return {"error": f"Unknown scenario: {scenario}"}

    # Insert events
    event_docs = []
    for evt in events:
        doc = {**evt}
        if isinstance(doc["timestamp"], str):
            doc["timestamp"] = datetime.fromisoformat(doc["timestamp"].replace("Z", "+00:00"))
        doc["_ingested_at"] = now
        doc["_source_topic"] = "FuelRetail-fraud-events"
        doc["_simulation"] = True
        event_docs.append(doc)

    await db["events"].insert_many(event_docs)
    logger.info("Local sim: inserted %d events for user %s", len(event_docs), uid)

    # Insert fraud_alert if fraud scenario
    if scenario in SIGNAL_META:
        meta = SIGNAL_META[scenario]
        alert_doc = {
            "alertId": f"alert-{meta['signal'].lower()}-{uid}-{uuid4().hex[:8]}",
            "userId": uid,
            "signal": meta["signal"],
            "severity": meta["severity"],
            "status": "open",
            "details": meta["details"],
            "ruleSnapshot": meta["ruleSnapshot"],
            "events": events,
            "createdAt": now,
            "_simulation": True,
        }
        await db["fraud_alerts"].insert_one(alert_doc)
        logger.info("Local sim: inserted fraud_alert signal=%s for user %s", meta["signal"], uid)

    return {
        "scenario": scenario,
        "userId": uid,
        "eventsProduced": len(events),
        "events": events,
        "mode": "local",
    }


async def _insert_alert(scenario: str, uid: str, events: list[dict], now: datetime):
    """Insert a fraud_alert directly into MongoDB (accelerates what ASP would produce)."""
    if scenario not in SIGNAL_META:
        return
    from backend.database import get_fraud_db
    db = get_fraud_db()
    meta = SIGNAL_META[scenario]
    alert_doc = {
        "alertId": f"alert-{meta['signal'].lower()}-{uid}-{uuid4().hex[:8]}",
        "userId": uid,
        "signal": meta["signal"],
        "severity": meta["severity"],
        "status": "open",
        "details": meta["details"],
        "ruleSnapshot": meta["ruleSnapshot"],
        "events": events,
        "createdAt": now,
    }
    await db["fraud_alerts"].insert_one(alert_doc)
    logger.info("Inserted fraud_alert signal=%s for user %s", meta["signal"], uid)


async def simulate_scenario(scenario: str, user_id: str | None = None) -> dict:
    """Produce a simulation scenario's events.

    Hybrid approach:
    1. Produce events to MSK via EC2 SSH (real pipeline — events flow through ASP).
    2. Insert the fraud_alert directly into MongoDB so the change stream fires immediately
       (ASP windowed processors can take minutes to flush; this accelerates the demo).
    Falls back to local-only if EC2 is unreachable.
    """
    uid = user_id or f"sim-user-{uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    if scenario not in ("signal_1", "signal_2", "signal_3", "signal_4", "clean"):
        return {"error": f"Unknown scenario: {scenario}"}

    events = _build_scenario_events(scenario, uid, now)

    # Try EC2 → MSK first
    ec2_ok = False
    ec2_result = None
    try:
        ec2_result = await _simulate_ec2(scenario, uid, now)
        ec2_ok = True
        logger.info("Events produced via EC2 → MSK: %s for %s", scenario, uid)
    except Exception as e:
        logger.warning("EC2/MSK unavailable (%s), falling back to local", e)

    # Insert alert directly for immediate change stream trigger
    if scenario != "clean":
        try:
            await _insert_alert(scenario, uid, events, now)
        except Exception as e:
            logger.error("Alert insert failed: %s", e)

    if ec2_ok:
        return ec2_result

    # Fallback: insert events locally too (EC2 was unreachable)
    try:
        result = await _simulate_local(scenario, uid, now)
        logger.info("Simulated locally: %s for %s", scenario, uid)
        return result
    except Exception as e:
        logger.error("Local simulation also failed: %s", e)
        return {"error": f"Simulation failed: {str(e)}"}
