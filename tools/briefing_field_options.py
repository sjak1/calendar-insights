"""
Allowed values for the controlled-vocabulary fields on a briefing's VISIT_INFO
form (Visit Type, Visit Focus, Program, Pillars, Sales Play).

These are stored as plain strings/arrays, but only values already in the tenant's
set are valid — writing an arbitrary string ("Prospect Ltd" for a Visit Type of
Prospect/Existing Customer/Analyst) stores something the UI can't resolve. Rather
than hardcode the lists (they bloat the prompt and drift), the values are read
live from existing briefings by aggregation, so the agent can fetch, pick a valid
one, and confirm with the user before it is written.

Read-only. The /lookupvalues API returns nothing for this tenant, so the source
of truth is the values already present on real records.
"""
from typing import Any, Dict, List

from logging_config import get_logger

logger = get_logger(__name__)

EVENTS_INDEX = "events"
_VISIT_INFO = "eventFormData.VISIT_INFO"

# field key -> (VISIT_INFO attribute, is the value multi-valued?)
FIELD_MAP = {
    "visit_type": ("visitType", False),
    "visit_focus": ("visitFocus", False),
    "program": ("program", False),
    "pillars": ("pillars", True),
    "sales_play": ("salesPlay", True),
}


def list_field_values(field: str) -> Dict[str, Any]:
    """
    Return the allowed values for one controlled briefing field, most-used first.

    field: one of visit_type, visit_focus, program, pillars, sales_play.
    """
    field = (field or "").strip().lower()
    mapping = FIELD_MAP.get(field)
    if mapping is None:
        return {
            "error": f"Unknown field '{field}'. Valid fields: {', '.join(FIELD_MAP)}.",
        }

    attr, multi = mapping
    try:
        from opensearch_client import search
    except ImportError:
        return {"error": "Search backend unavailable."}

    body = {
        "size": 0,
        "aggs": {"vals": {"terms": {"field": f"{_VISIT_INFO}.{attr}.keyword", "size": 100}}},
    }
    result = search(index=EVENTS_INDEX, body=body)
    if not result.get("success"):
        return {"error": f"Could not load values for {field}: {result.get('error')}"}

    buckets = (result.get("aggregations") or {}).get("vals", {}).get("buckets", [])
    values: List[str] = [b["key"] for b in buckets if b.get("key")]
    # Drop obvious junk the synthetic data carries (blank / "N/A")
    values = [v for v in values if v.strip() and v.strip().upper() != "N/A"]

    logger.info(f"briefing field options: {field} → {len(values)} value(s)")
    return {
        "field": field,
        "multivalue": multi,
        "allowed_values": values,
        "guidance": (
            "Choose only from allowed_values — an off-list value will not resolve in the UI. "
            + ("This field accepts several values; pass a list. " if multi else "")
            + "Confirm the choice with the user before it goes on the briefing."
        ),
    }
