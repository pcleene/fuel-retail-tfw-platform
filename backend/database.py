import logging
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import MongoClient

logger = logging.getLogger(__name__)

# ─── Motor client (UC1/UC3 backward compat) ─────────────────────
_client: AsyncIOMotorClient | None = None
_db_screening: AsyncIOMotorDatabase | None = None
_db_analytics: AsyncIOMotorDatabase | None = None
_db_fraud: AsyncIOMotorDatabase | None = None


async def connect(uri: str, screening_name: str, analytics_name: str, fraud_name: str,
                  tls_cert_path: str | None = None):
    global _client, _db_screening, _db_analytics, _db_fraud
    kwargs = {}
    if tls_cert_path:
        kwargs["tls"] = True
        kwargs["tlsCertificateKeyFile"] = tls_cert_path
    _client = AsyncIOMotorClient(uri, **kwargs)
    # verify connection
    await _client.admin.command("ping")
    _db_screening = _client[screening_name]
    _db_analytics = _client[analytics_name]
    _db_fraud = _client[fraud_name]
    logger.info("Connected to MongoDB Atlas (Motor)")


async def disconnect():
    global _client
    if _client:
        _client.close()
        logger.info("Disconnected from MongoDB Atlas (Motor)")


def get_screening_db() -> AsyncIOMotorDatabase:
    assert _db_screening is not None, "DB not initialised"
    return _db_screening


def get_analytics_db() -> AsyncIOMotorDatabase:
    assert _db_analytics is not None, "DB not initialised"
    return _db_analytics


def get_fraud_db() -> AsyncIOMotorDatabase:
    assert _db_fraud is not None, "DB not initialised"
    return _db_fraud


# ─── PyMongo sync client (UC2b: langgraph memory layer) ─────────
# langgraph-checkpoint-mongodb and langgraph-store-mongodb require a sync
# MongoClient. They provide async wrappers (aget, aput, etc.) internally.
_pymongo_client: MongoClient | None = None
_pymongo_screening_db = None


async def connect_pymongo(uri: str, screening_name: str, tls_cert_path: str | None = None):
    global _pymongo_client, _pymongo_screening_db
    kwargs = {}
    if tls_cert_path:
        kwargs["tls"] = True
        kwargs["tlsCertificateKeyFile"] = tls_cert_path
    _pymongo_client = MongoClient(uri, **kwargs)
    _pymongo_client.admin.command("ping")
    _pymongo_screening_db = _pymongo_client[screening_name]
    logger.info("Connected to MongoDB Atlas (PyMongo sync for langgraph)")


async def disconnect_pymongo():
    global _pymongo_client
    if _pymongo_client:
        _pymongo_client.close()
        logger.info("Disconnected from MongoDB Atlas (PyMongo sync)")


def get_pymongo_client() -> MongoClient:
    assert _pymongo_client is not None, "PyMongo client not initialised"
    return _pymongo_client


def get_pymongo_screening_db():
    assert _pymongo_screening_db is not None, "PyMongo screening DB not initialised"
    return _pymongo_screening_db
