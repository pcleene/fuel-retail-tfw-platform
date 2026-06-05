"""Standalone FastAPI app for UC2b Analytics Chatbot — runs on port 8002."""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.database import connect, disconnect, connect_pymongo, disconnect_pymongo

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup — Motor for async DB ops + sync pymongo for langgraph memory
    await connect(
        uri=settings.mongodb_url,
        screening_name=settings.screening_db,
        analytics_name=settings.analytics_db,
        fraud_name=settings.fraud_db,
        tls_cert_path=settings.tls_cert_path,
    )
    await connect_pymongo(
        uri=settings.mongodb_url,
        screening_name=settings.screening_db,
        tls_cert_path=settings.tls_cert_path,
    )
    from backend.services.analytics import init_memory_layer, close_mcp
    await init_memory_layer()
    logger.info("UC2b memory layer initialised")
    yield
    # Shutdown
    await close_mcp()
    await disconnect()
    await disconnect_pymongo()


app = FastAPI(title="FuelRetail Demo — Analytics Chatbot", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from backend.routers import analytics  # noqa: E402

app.include_router(analytics.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "analytics"}
