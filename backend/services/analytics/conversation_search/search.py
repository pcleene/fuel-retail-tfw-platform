"""
High-level search entry point — hybrid rankFusion with text-only fallback.
"""

import copy
import logging

from backend.config import settings
from backend.database import get_screening_db

from backend.services.analytics.conversation_search.pipeline import (
    build_search_pipeline,
    build_facet_meta_pipeline,
)
from backend.services.analytics.conversation_search.parsing import (
    parse_facets,
    parse_highlights,
    format_dt,
)

logger = logging.getLogger(__name__)


def get_query_embedding(query: str) -> list[float]:
    """Generate a Voyage AI embedding for the search query."""
    import voyageai
    client = voyageai.Client(api_key=settings.voyage_api_key)
    result = client.embed(
        [query], model=settings.voyage_model, output_dimension=settings.voyage_dimensions
    )
    return result.embeddings[0]


def _truncate_vectors_for_debug(pipeline: list[dict], max_items: int = 5) -> list[dict]:
    """Deep-copy the pipeline and truncate queryVector arrays for readable debug output.

    UI-only: feeds the debug panel in the frontend so 1024-dim vectors don't blow up the JSON viewer.
    """
    out = copy.deepcopy(pipeline)
    for stage in out:
        rf = stage.get("$rankFusion", {})
        pipelines = rf.get("input", {}).get("pipelines", {})
        for _name, steps in pipelines.items():
            for step in steps:
                vs = step.get("$vectorSearch", {})
                full = vs.get("queryVector")
                if full and len(full) > max_items:
                    vs["queryVector"] = full[:max_items] + [f"... ({len(full)} dims total)"]
    return out


async def _execute_pipeline(
    coll, pipeline: list[dict], query: str, filters: dict,
    use_facets: bool, limit: int, debug: bool,
) -> tuple[list, list, bool, str | None, int | None]:
    """Run the aggregation pipeline and return (results, facets, has_more, next_cursor, total_estimate)."""
    results = []
    facets: list = []
    has_more = False
    next_cursor = None
    total_estimate = None

    if use_facets:
        async for doc in coll.aggregate(pipeline):
            raw_results = doc.get("results", [])
            metadata = doc.get("metadata", [])

            has_more = len(raw_results) > limit
            if has_more:
                raw_results = raw_results[:limit]

            total_estimate = metadata[0]["total"] if metadata else 0

            for r in raw_results:
                r["highlights"] = parse_highlights(r.get("highlights", []))
                r["createdAt"] = format_dt(r.get("createdAt"))
                r["updatedAt"] = format_dt(r.get("updatedAt"))
                results.append(r)

        facet_pipeline = build_facet_meta_pipeline(query, filters)
        async for meta in coll.aggregate(facet_pipeline):
            facets = parse_facets(meta)

    else:
        async for doc in coll.aggregate(pipeline):
            results.append(doc)

        has_more = len(results) > limit
        if has_more:
            next_cursor = results[-1].get("paginationToken")
            results = results[:limit]

        for r in results:
            r["highlights"] = parse_highlights(r.get("highlights", []))
            r["createdAt"] = format_dt(r.get("createdAt"))
            r["updatedAt"] = format_dt(r.get("updatedAt"))
            r.pop("paginationToken", None)

    return results, facets, has_more, next_cursor, total_estimate


async def search_conversations(
    query: str = "",
    filters: dict | None = None,
    cursor: str | None = None,
    limit: int = 10,
    use_facets: bool = True,
    debug: bool = False,
) -> dict:
    """High-level search entry point with hybrid rankFusion search."""
    db = get_screening_db()
    coll = db["chat_conversations"]

    filters = filters or {}

    query_embedding = None
    if query.strip():
        try:
            query_embedding = get_query_embedding(query)
        except Exception as e:
            logger.warning("Failed to generate query embedding, falling back to text-only: %s", e)

    pipeline = build_search_pipeline(query, filters, use_facets, cursor, limit, query_embedding)

    debug_pipeline = _truncate_vectors_for_debug(pipeline) if debug else None
    debug_facet_pipeline = None

    results = []
    facets = []
    has_more = False
    next_cursor = None
    total_estimate = None

    try:
        results, facets, has_more, next_cursor, total_estimate = await _execute_pipeline(
            coll, pipeline, query, filters, use_facets, limit, debug,
        )
    except Exception as e:
        if query_embedding is not None:
            logger.warning("rankFusion search failed (%s), retrying text-only", e)
            pipeline = build_search_pipeline(query, filters, use_facets, cursor, limit, query_embedding=None)
            debug_pipeline = pipeline if debug else None
            try:
                results, facets, has_more, next_cursor, total_estimate = await _execute_pipeline(
                    coll, pipeline, query, filters, use_facets, limit, debug,
                )
            except Exception as e2:
                logger.error("Text-only fallback also failed: %s", e2)
        else:
            logger.error("Conversation search failed: %s", e)

    if debug:
        facet_pipeline = build_facet_meta_pipeline(query, filters)
        debug_facet_pipeline = facet_pipeline

    resp = {
        "results": results,
        "facets": facets,
        "pagination": {
            "hasMore": has_more,
            "nextCursor": next_cursor,
            "totalEstimate": total_estimate,
        },
    }
    if debug:
        resp["debugPipeline"] = debug_pipeline
        resp["debugFacetPipeline"] = debug_facet_pipeline
    return resp
