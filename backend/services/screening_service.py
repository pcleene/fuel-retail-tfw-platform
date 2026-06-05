"""
Name Screening Service — UC1
Bi-directional sanctions screening using Atlas Search fuzzy matching.

Flow 1 (check_new_user): Search a new user's name against sanctioned_list
Flow 2 (batch_sweep): Search all sanctioned names against user_profiles, flag matches in-place
"""
import logging
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

# ── Atlas Search index definitions ─────────────────────────────────
# Must be created manually in Atlas UI or via Admin API

MALAY_NAME_ANALYZER = {
    "name": "malay_name_analyzer",
    "charFilters": [
        {
            "type": "mapping",
            "mappings": {
                " bin ": " ", " binti ": " ", " a/l ": " ", " a/p ": " ",
                " anak lelaki ": " ", " anak perempuan ": " ",
                " Bin ": " ", " Binti ": " ", " A/L ": " ", " A/P ": " ",
                " BIN ": " ", " BINTI ": " ",
            },
        }
    ],
    "tokenizer": {"type": "standard"},
    "tokenFilters": [{"type": "lowercase"}],
}

PROFILES_FUZZY_INDEX = {
    "name": "profiles_fuzzy",
    "definition": {
        "mappings": {
            "dynamic": False,
            "fields": {
                "fullName": [
                    {
                        "type": "string",
                        "analyzer": "malay_name_analyzer",
                        "searchAnalyzer": "malay_name_analyzer",
                    },
                    {
                        "type": "autocomplete",
                        "analyzer": "malay_name_analyzer",
                        "tokenization": "edgeGram",
                        "minGrams": 2,
                        "maxGrams": 15,
                    },
                ],
                "dateOfBirth": {"type": "date"},
            },
        },
        "analyzers": [MALAY_NAME_ANALYZER],
    },
}

SANCTIONS_FUZZY_INDEX = {
    "name": "sanctions_fuzzy",
    "definition": {
        "mappings": {
            "dynamic": False,
            "fields": {
                "fullName": [
                    {
                        "type": "string",
                        "analyzer": "malay_name_analyzer",
                        "searchAnalyzer": "malay_name_analyzer",
                    },
                    {
                        "type": "autocomplete",
                        "analyzer": "malay_name_analyzer",
                        "tokenization": "edgeGram",
                        "minGrams": 2,
                        "maxGrams": 15,
                    },
                ],
                "aliases": [
                    {
                        "type": "string",
                        "analyzer": "malay_name_analyzer",
                        "searchAnalyzer": "malay_name_analyzer",
                    },
                    {
                        "type": "autocomplete",
                        "analyzer": "malay_name_analyzer",
                        "tokenization": "edgeGram",
                        "minGrams": 2,
                        "maxGrams": 15,
                    },
                ],
                "dateOfBirth": {"type": "date"},
            },
        },
        "analyzers": [MALAY_NAME_ANALYZER],
    },
}


class ScreeningService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.profiles = db["user_profiles"]
        self.sanctioned = db["sanctioned_list"]

    # ── Autocomplete ─────────────────────────────────────────────────
    async def autocomplete_sanctioned(self, query: str, limit: int = 8) -> list[dict]:
        """Type-ahead search against sanctioned_list fullName + aliases."""
        pipeline = [
            {
                "$search": {
                    "index": "sanctions_fuzzy",
                    "compound": {
                        "should": [
                            {
                                "autocomplete": {
                                    "query": query,
                                    "path": "fullName",
                                    "fuzzy": {"maxEdits": 1, "prefixLength": 1},
                                }
                            },
                            {
                                "autocomplete": {
                                    "query": query,
                                    "path": "aliases",
                                    "fuzzy": {"maxEdits": 1, "prefixLength": 1},
                                }
                            },
                        ],
                        "minimumShouldMatch": 1,
                    },
                }
            },
            {"$addFields": {"score": {"$meta": "searchScore"}}},
            {"$limit": limit},
            {
                "$project": {
                    "_id": 0,
                    "fullName": 1,
                    "aliases": 1,
                    "source": 1,
                    "country": 1,
                    "category": 1,
                    "score": 1,
                }
            },
        ]

        results = []
        async for doc in self.sanctioned.aggregate(pipeline):
            results.append(doc)
        return results

    async def autocomplete_profiles(self, query: str, limit: int = 8) -> list[dict]:
        """Type-ahead search against user_profiles fullName."""
        pipeline = [
            {
                "$search": {
                    "index": "profiles_fuzzy",
                    "autocomplete": {
                        "query": query,
                        "path": "fullName",
                        "fuzzy": {"maxEdits": 1, "prefixLength": 1},
                    },
                }
            },
            {"$addFields": {"score": {"$meta": "searchScore"}}},
            {"$limit": limit},
            {
                "$project": {
                    "_id": 0,
                    "userId": 1,
                    "fullName": 1,
                    "status": 1,
                    "score": 1,
                }
            },
        ]

        results = []
        async for doc in self.profiles.aggregate(pipeline):
            results.append(doc)
        return results

    # ── Flow 1: Check new user against sanctioned list ─────────────
    async def check_new_user(
        self, name: str, dob: str | None = None, max_edits: int = 2, limit: int = 10
    ) -> list[dict]:
        """Search a user's name against the sanctioned_list (onboarding check)."""
        compound: dict = {
            "should": [
                {
                    "text": {
                        "query": name,
                        "path": "fullName",
                        "fuzzy": {"maxEdits": max_edits, "prefixLength": 1},
                        "score": {"boost": {"value": 2}},
                    }
                },
                {
                    "text": {
                        "query": name,
                        "path": "aliases",
                        "fuzzy": {"maxEdits": max_edits, "prefixLength": 1},
                    }
                },
            ],
            "minimumShouldMatch": 1,
        }

        if dob:
            compound["filter"] = [
                {"equals": {"path": "dateOfBirth", "value": datetime.fromisoformat(dob)}}
            ]

        pipeline = [
            {"$search": {"index": "sanctions_fuzzy", "compound": compound}},
            {"$addFields": {"score": {"$meta": "searchScore"}}},
            {"$limit": limit},
            {
                "$project": {
                    "_id": 0,
                    "fullName": 1,
                    "aliases": 1,
                    "dateOfBirth": 1,
                    "country": 1,
                    "source": 1,
                    "category": 1,
                    "score": 1,
                }
            },
        ]

        results = []
        async for doc in self.sanctioned.aggregate(pipeline):
            if "dateOfBirth" in doc and doc["dateOfBirth"]:
                doc["dateOfBirth"] = doc["dateOfBirth"].isoformat()
            results.append(doc)
        return results

    # ── Flow 2: Batch watchlist sweep ──────────────────────────────
    # TODO: Parallelise with asyncio.gather — run 3-5 sanctioned entries
    # concurrently instead of sequentially. Each _search_profiles call is
    # an independent Atlas Search query, so batching would cut wall-clock
    # time roughly proportional to the concurrency level.
    async def batch_sweep(self, limit: int = 0) -> dict:
        """Sweep all sanctioned names against user_profiles. Flag matches in-place."""
        cursor = self.sanctioned.find({})
        if limit > 0:
            cursor = cursor.limit(limit)

        sanctioned_entries = await cursor.to_list(length=None)
        total_matches = 0
        flagged_user_ids: set[str] = set()
        match_details: list[dict] = []

        for entry in sanctioned_entries:
            names_to_check = [("primary", entry["fullName"])]
            for alias in entry.get("aliases", []):
                names_to_check.append(("alias", alias))

            for match_type, query_name in names_to_check:
                try:
                    matches = await self._search_profiles(query_name, max_edits=2, limit=10)
                    for m in matches:
                        if m["score"] > 0.5:
                            now = datetime.now(timezone.utc)
                            match_doc = {
                                "sanctionedName": entry["fullName"],
                                "source": entry.get("source", "unknown"),
                                "score": m["score"],
                                "matchedAgainst": query_name,
                                "matchType": match_type,
                                "detectedAt": now,
                            }
                            # Update user profile in-place
                            await self.profiles.update_one(
                                {"userId": m["userId"]},
                                {
                                    "$set": {
                                        "screening.lastScreenedAt": now,
                                        "screening.riskFlag": True,
                                    },
                                    "$push": {"screening.matches": match_doc},
                                },
                            )
                            total_matches += 1
                            flagged_user_ids.add(m["userId"])
                            match_details.append({
                                "userId": m["userId"],
                                "userFullName": m["fullName"],
                                "sanctionedName": entry["fullName"],
                                "source": entry.get("source"),
                                "score": m["score"],
                                "matchedAgainst": query_name,
                                "matchType": match_type,
                            })
                except Exception as e:
                    logger.warning(f"Search failed for '{query_name}': {e}")

        return {
            "sanctionedChecked": len(sanctioned_entries),
            "totalMatches": total_matches,
            "flaggedUsers": len(flagged_user_ids),
            "matches": match_details,
            "screenedAt": datetime.now(timezone.utc).isoformat(),
        }

    async def _search_profiles(
        self, query: str, max_edits: int = 2, limit: int = 10
    ) -> list[dict]:
        """Internal: fuzzy search a name against user_profiles collection."""
        pipeline = [
            {
                "$search": {
                    "index": "profiles_fuzzy",
                    "compound": {
                        "must": [
                            {
                                "text": {
                                    "query": query,
                                    "path": "fullName",
                                    "fuzzy": {"maxEdits": max_edits, "prefixLength": 1},
                                }
                            }
                        ]
                    },
                }
            },
            {"$addFields": {"score": {"$meta": "searchScore"}}},
            {"$limit": limit},
            {
                "$project": {
                    "_id": 0,
                    "userId": 1,
                    "fullName": 1,
                    "dateOfBirth": 1,
                    "score": 1,
                    "email": 1,
                    "phone": 1,
                    "status": 1,
                    "kyc": 1,
                    "wallet": 1,
                    "screening": 1,
                }
            },
        ]

        results = []
        async for doc in self.profiles.aggregate(pipeline):
            if "dateOfBirth" in doc and doc["dateOfBirth"]:
                doc["dateOfBirth"] = doc["dateOfBirth"].isoformat()
            results.append(doc)
        return results

    # ── Flagged users ──────────────────────────────────────────────
    async def get_flagged_users(self, limit: int = 100) -> list[dict]:
        """Return user profiles where screening.riskFlag is true."""
        cursor = self.profiles.find(
            {"screening.riskFlag": True},
            {"_id": 0},
        ).sort("screening.lastScreenedAt", -1).limit(limit)

        results = []
        async for doc in cursor:
            _serialize_dates(doc)
            results.append(doc)
        return results

    # ── Sanctioned list ────────────────────────────────────────────
    async def get_sanctioned(self, limit: int = 100, skip: int = 0) -> list[dict]:
        """Return paginated sanctioned entries."""
        cursor = self.sanctioned.find(
            {}, {"_id": 0}
        ).sort("addedAt", -1).skip(skip).limit(limit)

        results = []
        async for doc in cursor:
            _serialize_dates(doc)
            results.append(doc)
        return results

    # ── Dashboard stats ────────────────────────────────────────────
    async def get_stats(self) -> dict:
        profile_count = await self.profiles.count_documents({})
        sanctioned_count = await self.sanctioned.count_documents({})
        flagged_count = await self.profiles.count_documents({"screening.riskFlag": True})

        # Source breakdown
        source_pipeline = [
            {"$group": {"_id": "$source", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]
        sources = {}
        async for doc in self.sanctioned.aggregate(source_pipeline):
            sources[doc["_id"] or "unknown"] = doc["count"]

        # Last screening timestamp
        last_screened_doc = await self.profiles.find_one(
            {"screening.lastScreenedAt": {"$exists": True}},
            sort=[("screening.lastScreenedAt", -1)],
        )
        last_run = None
        if last_screened_doc:
            ts = last_screened_doc.get("screening", {}).get("lastScreenedAt")
            if ts:
                last_run = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)

        return {
            "totalProfiles": profile_count,
            "sanctionedEntries": sanctioned_count,
            "flaggedUsers": flagged_count,
            "sourceBreakdown": sources,
            "lastRun": last_run,
        }

    # ── Index definitions (educational) ────────────────────────────
    def get_index_definitions(self) -> dict:
        return {
            "profiles_fuzzy": PROFILES_FUZZY_INDEX,
            "sanctions_fuzzy": SANCTIONS_FUZZY_INDEX,
        }


def _serialize_dates(doc: dict) -> None:
    """Recursively convert datetime objects to ISO strings for JSON."""
    for key, value in doc.items():
        if isinstance(value, datetime):
            doc[key] = value.isoformat()
        elif isinstance(value, dict):
            _serialize_dates(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _serialize_dates(item)
