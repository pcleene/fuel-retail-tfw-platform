"""
Result parsing — facets, highlights, and datetime formatting.
"""

from datetime import datetime


def parse_facets(search_meta: dict) -> list[dict]:
    """Transform $$SEARCH_META facet output into structured format."""
    facet_results = search_meta.get("facet", {})
    parsed = []

    facet_name_map = {
        "categoryFacet": ("category", "Category"),
        "topicsFacet": ("topics", "Topics"),
        "queryTypesFacet": ("queryTypes", "Query Type"),
        "complexityFacet": ("complexity", "Complexity"),
        "intentFacet": ("intent", "Intent"),
        "collectionsFacet": ("collections", "Collections"),
        "turnCountFacet": ("turnCount", "Turns"),
    }

    for facet_name, (field, label) in facet_name_map.items():
        facet_data = facet_results.get(facet_name, {})
        buckets = facet_data.get("buckets", [])
        if buckets:
            parsed.append({
                "field": field,
                "label": label,
                "buckets": [
                    {"value": str(b.get("_id", "")), "count": b.get("count", 0)}
                    for b in buckets
                    if b.get("count", 0) > 0
                ],
            })

    return parsed


def parse_highlights(raw_highlights: list) -> list[dict]:
    """Convert Atlas Search highlights into structured format."""
    result = []
    for h in raw_highlights:
        result.append({
            "path": h.get("path", ""),
            "texts": [
                {"value": t.get("value", ""), "type": t.get("type", "text")}
                for t in h.get("texts", [])
            ],
        })
    return result


def format_dt(dt) -> str | None:
    """Format a datetime to ISO string, handling None and already-formatted strings."""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)
