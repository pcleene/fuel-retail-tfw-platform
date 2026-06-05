"""Standalone screening FastAPI app — runs independently on its own port."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers.screening import router as screening_router

app = FastAPI(title="FuelRetail Screening")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(screening_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
