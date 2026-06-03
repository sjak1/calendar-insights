"""
Shared event-id resolution + event data fetching.

Why this module exists:
  The frontend sends event_id as a UUID (e.g. 'A871AFA5-BF44-...'), but the
  OpenSearch events index keys events by a numeric id stored at top-level
  `eventId`. A SQL table (`m_request_master.unique_id` → `id`) maps between
  the two. Multiple tools (agenda_generator, drafts, presenter_suggest) all
  need this same plumbing — keep it in one place so the schema stays in sync.
"""

from typing import Any, Dict, List, Optional

from sqlalchemy import text

from database import engine
from logging_config import get_logger

logger = get_logger(__name__)

try:
    from opensearch_client import search as os_search
except ImportError:
    os_search = None


# Source field list — kept in one place so all consumers see the same fields.
# NOTE: Real customer/host data lives under `eventFormData.VISIT_INFO` (a list),
# NOT `eventData.VISIT_INFO.data` (empty in current data). Some older docs may
# still populate the latter — keep both for safety, prefer the former.
EVENT_SOURCE_FIELDS: List[str] = [
    "eventId",
    "eventName",
    "startTime",
    "endTime",
    "duration",
    "timezone",
    "status.stateName",
    "location.data",
    "eventFormData.VISIT_INFO",
    "eventFormData.EVENTS_VISIT_INFO",
    "eventFormData.EXTERNAL_ATTENDEES",
    "eventFormData.INTERNAL_ATTENDEES",
    "eventFormData.Opportunity",
    # Legacy fallbacks — empty in current data, kept for older docs.
    "eventData.VISIT_INFO.data",
    "eventData.EXTERNAL_ATTENDEES.data",
    "eventData.INTERNAL_ATTENDEES.data",
]


def _deep_get(obj: Any, dotted_path: str) -> Any:
    """Traverse nested dicts/lists by dotted key path (e.g. 'a.b.c').
    For lists, picks the first element — mirrors the helper in agenda_generator.
    """
    for key in dotted_path.split("."):
        if isinstance(obj, list):
            obj = obj[0] if obj else None
        if isinstance(obj, dict):
            obj = obj.get(key)
        else:
            return None
    return obj


def resolve_event_id(event_id: Optional[str]) -> Optional[str]:
    """
    Resolve event_id to the form OpenSearch indexes (CBR-style `event_number`).

    Accepts:
      - CBR-style id ('CBR-20260511-4216') → returned as-is
      - Numeric id ('14626365538') → looked up in `m_request_master.id` → `event_number`
      - UUID ('A871AFA5-BF44-45C3-8838-2BF4C1519AA5') → looked up in
        `m_request_master.unique_id` → `event_number`
      - Anything else → returned as-is (best-effort)

    Returns CBR-style event_number, or None if not found.
    """
    if not event_id:
        return None

    # Already CBR-style
    if isinstance(event_id, str) and event_id.startswith("CBR-"):
        return event_id

    is_uuid = "-" in event_id and len(event_id) == 36
    is_numeric = event_id.isdigit()

    if not (is_uuid or is_numeric):
        return event_id

    where_col = "unique_id" if is_uuid else "id"
    logger.info(f"Resolving {('UUID' if is_uuid else 'numeric id')} via m_request_master.{where_col}: {event_id}")
    try:
        with engine.connect() as conn:
            query = text(
                f"SELECT event_number FROM m_request_master "
                f"WHERE UPPER({where_col}) = UPPER(:val)"
            )
            row = conn.execute(query, {"val": event_id}).fetchone()
            if row and row[0]:
                cbr_id = str(row[0])
                logger.info(f"Resolved {event_id} → {cbr_id}")
                return cbr_id
            logger.warning(f"Not found in m_request_master.{where_col}: {event_id}")
            return None
    except Exception as e:
        logger.error(f"Error resolving event_id: {e}")
        return None


def fetch_event_data(event_id: Optional[str]) -> Dict[str, Any]:
    """
    Fetch a single event from the OpenSearch events index.

    Automatically resolves UUID → numeric id via `resolve_event_id` before
    querying. Returns a flat dict with the most commonly needed fields
    surfaced at the top level (so callers don't have to know the nested
    schema). Returns `{}` on miss / failure.

    Shape of return:
      {
        "event_id":     <str>,
        "event_name":   <str>,
        "customer_name":     <str>,
        "customer_industry": <str>,
        "visit_focus":       <str>,
        "meeting_objective": <str>,
        "host_name":  <str>,
        "host_email": <str>,
        "host_business_title": <str>,
        "num_attendees":      <int|None>,
        "start_time_ms":      <int>,
        "end_time_ms":        <int>,
        "timezone":           <str>,
        "location_name":      <str>,
        "location_address":   <str>,
        "external_attendees": [<dict>, ...],
        "internal_attendees": [<dict>, ...],
        "_raw":               <full hit source — for callers needing more>
      }
    """
    if not event_id:
        return {}

    if os_search is None:
        logger.warning("OpenSearch client not available — cannot fetch event data")
        return {}

    numeric_id = resolve_event_id(event_id)
    if not numeric_id:
        logger.warning(f"Could not resolve event_id: {event_id}")
        return {}

    body = {
        "query": {"term": {"eventId.keyword": numeric_id}},
        "size": 1,
        "_source": EVENT_SOURCE_FIELDS,
    }

    resp = os_search(index="events", body=body, size_cap=1)
    if not resp.get("success") or not resp.get("hits"):
        logger.warning(f"No event found in OpenSearch for id={numeric_id}")
        return {}

    src = resp["hits"][0].get("source", {})

    # Customer / host data lives in eventFormData.VISIT_INFO (a list of dicts).
    # Older docs MIGHT have eventData.VISIT_INFO.data populated — merge as fallback.
    visit_list = src.get("eventFormData", {}).get("VISIT_INFO") or []
    visit = visit_list[0] if isinstance(visit_list, list) and visit_list else {}
    visit_fallback = _deep_get(src, "eventData.VISIT_INFO.data") or {}
    # `visit` takes precedence; fallback fills gaps
    def vget(key):
        return visit.get(key) or visit_fallback.get(key)

    loc = _deep_get(src, "location.data") or {}

    def _normalize_list(val):
        if isinstance(val, list):
            return val
        if isinstance(val, dict):
            return [val]
        return []

    # Attendees live in eventFormData.{...}_ATTENDEES (a list); fall back to the
    # empty legacy eventData path only for older docs.
    external = _normalize_list(
        src.get("eventFormData", {}).get("EXTERNAL_ATTENDEES")
        or _deep_get(src, "eventData.EXTERNAL_ATTENDEES.data")
    )
    internal = _normalize_list(
        src.get("eventFormData", {}).get("INTERNAL_ATTENDEES")
        or _deep_get(src, "eventData.INTERNAL_ATTENDEES.data")
    )

    address = (
        loc.get("addressLine1") or loc.get("address") or loc.get("textField2") or ""
    )

    # `customer_name` sometimes lives in textField1 (e.g. "Lamborghini") when customerName is None
    return {
        "event_id":            src.get("eventId"),
        "event_name":          src.get("eventName"),
        "customer_name":       vget("customerName") or vget("textField1") or src.get("eventName"),
        "customer_industry":   vget("customerIndustry"),
        "visit_focus":         vget("visitFocus"),
        "meeting_objective":   vget("meetingObjective"),
        "host_name":           vget("oracleHostName"),
        "host_email":          vget("oracleHostEmail"),
        "host_business_title": vget("oracleHostBusinessTitle"),
        "requester_email":     vget("requesterEmail"),
        "num_attendees":       vget("numberOfAttendees"),
        "start_time_ms":       src.get("startTime"),
        "end_time_ms":         src.get("endTime"),
        "timezone":            src.get("timezone"),
        "location_name":       loc.get("locationName") or loc.get("textField1"),
        "location_address":    address,
        "external_attendees":  external,
        "internal_attendees":  internal,
        "_raw":                src,
    }
