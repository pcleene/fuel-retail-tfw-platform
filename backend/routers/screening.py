from fastapi import APIRouter
from motor.motor_asyncio import AsyncIOMotorClient
from backend.services.screening_service import ScreeningService
from backend.models.screening import CheckUserRequest, BatchSweepRequest

router = APIRouter(prefix="/api/screening", tags=["screening"])

# Screening uses testcluster (separate from fraud/analytics on cluster0)
_SCREENING_URI = "mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>"
_TLS_CERT = "<local-path>"
_DB_NAME = "FuelRetail_screening"

_client: AsyncIOMotorClient | None = None


def _get_db():
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(_SCREENING_URI, tls=True, tlsCertificateKeyFile=_TLS_CERT)
    return _client[_DB_NAME]


def _svc():
    return ScreeningService(_get_db())


@router.get("/autocomplete/sanctioned")
async def autocomplete_sanctioned(q: str, limit: int = 8):
    svc = _svc()
    return await svc.autocomplete_sanctioned(q, limit)


@router.get("/autocomplete/profiles")
async def autocomplete_profiles(q: str, limit: int = 8):
    svc = _svc()
    return await svc.autocomplete_profiles(q, limit)


@router.post("/check-user")
async def check_user(req: CheckUserRequest):
    svc = _svc()
    matches = await svc.check_new_user(req.name, req.dob, req.max_edits, req.limit)
    return {"query": req.name, "maxEdits": req.max_edits, "matches": matches}


@router.post("/batch-sweep")
async def batch_sweep(req: BatchSweepRequest | None = None):
    svc = _svc()
    limit = req.limit if req else 0
    return await svc.batch_sweep(limit)


@router.get("/flagged-users")
async def flagged_users(limit: int = 100):
    svc = _svc()
    return await svc.get_flagged_users(limit)


@router.get("/stats")
async def get_stats():
    svc = _svc()
    return await svc.get_stats()


@router.get("/index-definitions")
async def get_index_definitions():
    svc = _svc()
    return svc.get_index_definitions()


@router.get("/sanctioned")
async def get_sanctioned(limit: int = 100, skip: int = 0):
    svc = _svc()
    return await svc.get_sanctioned(limit, skip)
