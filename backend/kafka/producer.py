"""Kafka producer — sends fraud events to Amazon MSK via IAM auth (OAUTHBEARER).

Reuses the same MSK cluster as the EnergyOperator Demo demo.
"""

from __future__ import annotations

import json
import logging
import ssl
from datetime import datetime, timezone
from uuid import uuid4

from aiokafka import AIOKafkaProducer
from aiokafka.abc import AbstractTokenProvider
from aws_msk_iam_sasl_signer import MSKAuthTokenProvider

from backend.config import settings

logger = logging.getLogger(__name__)

AWS_REGION = "ap-southeast-1"

_producer: AIOKafkaProducer | None = None


class MSKTokenProvider(AbstractTokenProvider):
    """aiokafka-compatible OAUTHBEARER token provider using AWS IAM."""

    async def token(self):
        auth_token, _expiry_ms = MSKAuthTokenProvider.generate_auth_token(AWS_REGION)
        return auth_token


def _json_serializer(value):
    return json.dumps(value, default=str).encode("utf-8")


async def get_producer() -> AIOKafkaProducer:
    """Get or create a singleton Kafka producer."""
    global _producer
    if _producer is not None:
        return _producer

    brokers = settings.kafka_bootstrap_servers
    if not brokers:
        raise RuntimeError("KAFKA_BOOTSTRAP_SERVERS not set.")

    ssl_context = ssl.create_default_context()

    _producer = AIOKafkaProducer(
        bootstrap_servers=brokers,
        security_protocol="SASL_SSL",
        sasl_mechanism="OAUTHBEARER",
        sasl_oauth_token_provider=MSKTokenProvider(),
        ssl_context=ssl_context,
        value_serializer=_json_serializer,
        key_serializer=lambda k: k.encode("utf-8") if k else None,
    )
    await _producer.start()
    logger.info("Kafka producer connected to %s", brokers)
    return _producer


async def stop_producer():
    """Stop the singleton producer (call on app shutdown)."""
    global _producer
    if _producer:
        await _producer.stop()
        _producer = None
        logger.info("Kafka producer stopped")


async def produce_event(
    name: str,
    user_id: str,
    properties: dict,
    metadata: dict | None = None,
    timestamp: datetime | None = None,
) -> dict:
    """Produce a single event to MSK and return the event payload."""
    producer = await get_producer()
    ts = timestamp or datetime.now(timezone.utc)

    event = {
        "eventId": str(uuid4()),
        "origin": "FuelRetail-app",
        "name": name,
        "user_id": user_id,
        "timestamp": ts.isoformat(),
        "properties": properties,
        "metadata": metadata or {
            "device": "iPhone 15",
            "ip": "203.0.113.42",
            "sessionId": f"sess-{uuid4().hex[:8]}",
        },
    }

    await producer.send(
        settings.kafka_topic,
        value=event,
        key=user_id,
    )
    logger.info("Produced event %s for user %s to topic %s", name, user_id, settings.kafka_topic)
    return event
