"""
Atlas Search and $rankFusion pipeline builders.
"""

# UI-only: maps facet keys to the labels and filter params used by the frontend sidebar.
CONVERSATION_FACET_MAPPING = {
    "category": {"label": "Category", "key": "category", "filterParam": "category"},
    "topics": {"label": "Topics", "key": "topics", "filterParam": "topics"},
    "queryTypes": {"label": "Query Type", "key": "queryTypes", "filterParam": "queryTypes"},
    "complexity": {"label": "Complexity", "key": "complexity", "filterParam": "complexity"},
    "intent": {"label": "Intent", "key": "intent", "filterParam": "intent"},
    "collections": {"label": "Collections", "key": "collections", "filterParam": "collections"},
}

HIGHLIGHT_PATHS = [
    "messages.content",
    "summary",
    "title",
    "lastQuestion",
    "messages.mql",
]

RESULT_PROJECT = {
    "_id": 0,
    "threadId": 1,
    "title": 1,
    "summary": 1,
    "lastQuestion": 1,
    "category": 1,
    "complexity": 1,
    "intent": 1,
    "topics": 1,
    "collections": 1,
    "turnCount": 1,
    "createdAt": 1,
    "updatedAt": 1,
    "score": 1,
    "highlights": 1,
}

TEXT_PATHS = ["title", "summary", "lastQuestion", "messages.content", "messages.question", "messages.mql"]

VECTOR_INDEX_NAME = "conversation_vector"


# ─── Filter Building ─────────────────────────────────────────────

def build_filter_clauses(filters: dict) -> list[dict]:
    """Build Atlas Search filter clauses from user-supplied filters."""
    clauses = []
    for field, values in filters.items():
        if not values:
            continue
        if isinstance(values, str):
            values = [values]
        if len(values) == 1:
            clauses.append({"equals": {"path": field, "value": values[0]}})
        else:
            clauses.append({
                "compound": {
                    "should": [{"equals": {"path": field, "value": v}} for v in values],
                    "minimumShouldMatch": 1,
                }
            })
    return clauses


def _build_mql_filter(filters: dict) -> dict:
    """Convert user filter dict to standard MQL for $vectorSearch filter."""
    mql: dict = {}
    for field, values in filters.items():
        if not values:
            continue
        if isinstance(values, str):
            values = [values]
        mql[field] = values[0] if len(values) == 1 else {"$in": values}
    return mql


# ─── Stage Builders ──────────────────────────────────────────────

def _build_text_search_stage(
    query: str, filters: dict, filter_clauses: list[dict],
) -> dict:
    """Build a plain $search stage (text or exists, no rankFusion)."""
    if query.strip():
        text_operator: dict = {
            "text": {
                "query": query,
                "path": TEXT_PATHS,
                "fuzzy": {"maxEdits": 1},
            }
        }
    else:
        text_operator = {"exists": {"path": "threadId"}}

    if filter_clauses:
        search_operator: dict = {
            "compound": {
                "must": [text_operator],
                "filter": filter_clauses,
            }
        }
    else:
        search_operator = text_operator

    stage: dict = {"$search": {"index": "conversation_search"}}
    op_key = list(search_operator.keys())[0]
    stage["$search"][op_key] = search_operator[op_key]
    return stage


def _build_rankfusion_pipeline(
    query: str, filters: dict, filter_clauses: list[dict],
    query_embedding: list[float], limit: int,
) -> list[dict]:
    """Build a $rankFusion pipeline (MongoDB 8.0+) combining $search + $vectorSearch."""

    text_search_stage: dict = {"$search": {"index": "conversation_search"}}
    if filter_clauses:
        text_search_stage["$search"]["compound"] = {
            "must": [{
                "text": {
                    "query": query,
                    "path": TEXT_PATHS,
                    "fuzzy": {"maxEdits": 1},
                }
            }],
            "filter": filter_clauses,
        }
    else:
        text_search_stage["$search"]["text"] = {
            "query": query,
            "path": TEXT_PATHS,
            "fuzzy": {"maxEdits": 1},
        }

    vector_search_stage: dict = {
        "$vectorSearch": {
            "index": VECTOR_INDEX_NAME,
            "path": "searchEmbedding",
            "queryVector": query_embedding,
            "numCandidates": 50,
            "limit": limit + 1,
        }
    }
    mql_filter = _build_mql_filter(filters)
    if mql_filter:
        vector_search_stage["$vectorSearch"]["filter"] = mql_filter

    return [
        {
            "$rankFusion": {
                "input": {
                    "pipelines": {
                        "textSearch": [
                            text_search_stage,
                            {"$limit": limit + 1},
                        ],
                        "vectorSearch": [
                            vector_search_stage,
                        ],
                    }
                },
            }
        },
    ]


# ─── Top-Level Pipeline Assembly ─────────────────────────────────

def build_search_pipeline(
    query: str,
    filters: dict,
    use_facets: bool = True,
    cursor: str | None = None,
    limit: int = 10,
    query_embedding: list[float] | None = None,
) -> list[dict]:
    """Build the aggregation pipeline — uses $rankFusion for hybrid search when possible."""

    filter_clauses = build_filter_clauses(filters)
    has_query = bool(query.strip())
    use_rankfusion = has_query and query_embedding is not None

    if use_rankfusion and use_facets:
        pipeline = _build_rankfusion_pipeline(
            query, filters, filter_clauses, query_embedding, limit,
        )
        pipeline.extend([
            {"$addFields": {"score": {"$meta": "score"}}},
            {"$facet": {
                "results": [
                    {"$limit": limit + 1},
                    {"$project": RESULT_PROJECT},
                ],
                "metadata": [{"$count": "total"}],
            }},
        ])
        return pipeline

    search_stage = _build_text_search_stage(query, filters, filter_clauses)
    pipeline = []

    if use_facets:
        pipeline.append(search_stage)
        pipeline.extend([
            {"$addFields": {
                "score": {"$meta": "searchScore"},
                "highlights": {"$meta": "searchHighlights"},
            }},
            {"$sort": {"score": -1}},
            {"$facet": {
                "results": [
                    {"$limit": limit + 1},
                    {"$project": RESULT_PROJECT},
                ],
                "metadata": [{"$count": "total"}],
            }},
        ])
    else:
        search_stage["$search"]["highlight"] = {"path": HIGHLIGHT_PATHS}
        if cursor:
            search_stage["$search"]["searchAfter"] = cursor

        pipeline.append(search_stage)
        pipeline.extend([
            {"$addFields": {
                "score": {"$meta": "searchScore"},
                "highlights": {"$meta": "searchHighlights"},
                "paginationToken": {"$meta": "searchSequenceToken"},
            }},
            {"$limit": limit + 1},
            {"$project": {**RESULT_PROJECT, "paginationToken": 1}},
        ])

    return pipeline


def build_facet_meta_pipeline(query: str, filters: dict) -> list[dict]:
    """Build a $searchMeta pipeline to get facet counts."""
    filter_clauses = build_filter_clauses(filters)

    if query.strip():
        text_operator = {
            "text": {
                "query": query,
                "path": ["title", "summary", "lastQuestion", "messages.content"],
                "fuzzy": {"maxEdits": 1},
            }
        }
    else:
        text_operator = {"exists": {"path": "threadId"}}

    if filter_clauses:
        search_operator = {
            "compound": {
                "must": [text_operator],
                "filter": filter_clauses,
            }
        }
    else:
        search_operator = text_operator

    return [{
        "$searchMeta": {
            "index": "conversation_search",
            "facet": {
                "operator": search_operator,
                "facets": {
                    "categoryFacet": {"type": "string", "path": "category"},
                    "topicsFacet": {"type": "string", "path": "topics"},
                    "queryTypesFacet": {"type": "string", "path": "queryTypes"},
                    "complexityFacet": {"type": "string", "path": "complexity"},
                    "intentFacet": {"type": "string", "path": "intent"},
                    "collectionsFacet": {"type": "string", "path": "collections"},
                    "turnCountFacet": {
                        "type": "number",
                        "path": "turnCount",
                        "boundaries": [1, 3, 6, 10, 20],
                        "default": "other",
                    },
                },
            },
        }
    }]
