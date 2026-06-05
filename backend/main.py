"""Shared FastAPI app — lifespan, CORS, includes all routers."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import StreamingResponse

from backend.config import settings
from backend.database import connect, disconnect, connect_pymongo, disconnect_pymongo, get_fraud_db
from backend.services.change_stream_watcher import init_watcher, get_watcher

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
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

    from backend.services.analytics import init_memory_layer, close_mcp, seed_app_users
    await init_memory_layer()
    await seed_app_users()
    logger.info("UC2b memory layer initialised")

    watcher = init_watcher(get_fraud_db())
    watcher.start()
    logger.info("Change stream watcher started")

    yield

    await close_mcp()
    await watcher.stop()
    await disconnect()
    await disconnect_pymongo()


app = FastAPI(title="FuelRetail Demo", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
from backend.routers import screening, analytics, fraud  # noqa: E402

app.include_router(screening.router)
app.include_router(analytics.router)
app.include_router(fraud.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/fraud/events/stream")
async def fraud_event_stream():
    """SSE endpoint for real-time fraud alerts and investigation updates."""
    watcher = get_watcher()
    queue = watcher.subscribe()

    async def event_generator():
        try:
            yield f"event: connected\ndata: {json.dumps({'status': 'connected'})}\n\n"
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=30.0)
                    event_type = message["event"]
                    data = json.dumps(message["data"], default=str)
                    yield f"event: {event_type}\ndata: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            watcher.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
