"""
Presenter suggestion engine — queries OpenSearch activities index to find
presenters who have presented on matching topics or at matching events.
"""

import re
from typing import Any, Dict, List, Optional

from logging_config import get_logger

logger = get_logger(__name__)

ACTIVITIES_INDEX = "activities"
EVENTS_INDEX = "events"

# Activity index field paths (verified against real documents)
TOPIC_NAME = "activityInfo.topic.data.topic.textField1"
PRESENTER_LIST = "activityInfo.topic_presenter"
PRESENTER_EMAIL_FIELD = "activityInfo.topic_presenter.data.presenter.primaryEmail"
ACT_IS_CLEVEL = "activityInfo.EVENTS_VISIT_INFO.data.isCLevelAttendee"
EVENT_ID = "eventId"
START_TIME = "startTime.utcMs"

# Events index field paths
EVT_CUSTOMER_NAME = "eventData.VISIT_INFO.data.customerName"
EVT_CUSTOMER_INDUSTRY = "eventData.VISIT_INFO.data.customerIndustry"
EVT_EVENT_NAME = "eventData.VISIT_INFO.data.eventName"

# Max events to pull when resolving customer/industry → event_ids
_MAX_SCOPE_EVENTS = 50

# Presenter statuses to exclude (don't suggest people who declined)
_EXCLUDED_STATUSES = {"declined", "rejected", "cancelled"}

# Audience-level signals
AUDIENCE_C_LEVEL = "c_level"
AUDIENCE_VP_PLUS = "vp_plus"
AUDIENCE_SENIOR = "senior"
_AUDIENCE_LEVELS = {AUDIENCE_C_LEVEL, AUDIENCE_VP_PLUS, AUDIENCE_SENIOR}

# Seniority tiers derived from presenter title. Higher = more senior.
# Tier 3: C-suite / President / Chief (but NOT "Vice President")
# Tier 2: VP / EVP / SVP
# Tier 1: Director / Head of / Managing
# Tier 0: everyone else
_VP_RE = re.compile(r"\bvice\s+president\b|\b[se]vp\b|\bvp\b", re.IGNORECASE)
_CHIEF_RE = re.compile(r"\b(ceo|cfo|cto|cio|coo|cmo|cxo|chief)\b", re.IGNORECASE)
_PRESIDENT_RE = re.compile(r"\bpresident\b", re.IGNORECASE)
_TIER1_RE = re.compile(r"\b(director|head\s+of|managing)\b", re.IGNORECASE)


def _presenter_seniority(title: str) -> int:
    """Rough seniority tier from a presenter's designation. Higher = more senior."""
    if not title:
        return 0
    t = title.lower()
    is_vp = bool(_VP_RE.search(t))
    # Tier 3 needs Chief/C-suite OR "President" that isn't part of "Vice President"
    if _CHIEF_RE.search(t) or (_PRESIDENT_RE.search(t) and not is_vp):
        return 3
    if is_vp:
        return 2
    if _TIER1_RE.search(t):
        return 1
    return 0


def _min_seniority_for_audience(audience_level: Optional[str]) -> int:
    """Minimum presenter seniority tier we consider a strong match for a given audience."""
    if audience_level == AUDIENCE_C_LEVEL:
        return 3
    if audience_level == AUDIENCE_VP_PLUS:
        return 2
    if audience_level == AUDIENCE_SENIOR:
        return 1
    return 0


def _deep_get(d: Any, path: str) -> Any:
    """Retrieve a nested value from a dict using dot-separated path."""
    for key in path.split("."):
        if isinstance(d, dict):
            d = d.get(key)
        else:
            return None
    return d


def _fetch_event_ids_by_scope(
    customer_name: Optional[str],
    industry: Optional[str],
) -> List[str]:
    """
    Query the events index for events matching customer or industry.
    Returns up to _MAX_SCOPE_EVENTS event_ids.
    """
    try:
        from opensearch_client import search
    except ImportError:
        return []

    should = []
    if customer_name:
        should.append(
            {"term": {f"{EVT_CUSTOMER_NAME}.keyword": {"value": customer_name, "boost": 3}}}
        )
        should.append(
            {"match": {EVT_CUSTOMER_NAME: {"query": customer_name, "fuzziness": "AUTO"}}}
        )
    if industry:
        should.append(
            {"term": {f"{EVT_CUSTOMER_INDUSTRY}.keyword": {"value": industry, "boost": 2}}}
        )

    if not should:
        return []

    body = {
        "query": {"bool": {"should": should, "minimum_should_match": 1}},
        "_source": False,
        "size": _MAX_SCOPE_EVENTS,
    }

    result = search(index=EVENTS_INDEX, body=body)
    if not result.get("success"):
        logger.warning(f"Event scope lookup failed: {result.get('error')}")
        return []

    event_ids = [h.get("id") for h in result.get("hits", []) if h.get("id")]
    logger.info(
        f"Scope lookup: customer={customer_name}, industry={industry} → {len(event_ids)} events"
    )
    return event_ids


def _build_activity_query(
    topic: Optional[str],
    event_ids: Optional[List[str]],
    audience_level: Optional[str] = None,
) -> Dict[str, Any]:
    """Build OpenSearch query for the activities index.

    When audience_level is supplied, activities attended by a matching audience
    are boosted (not required) — so we still get results if nobody has a
    perfectly-matching history.
    """
    must: List[Dict[str, Any]] = [
        {"exists": {"field": PRESENTER_EMAIL_FIELD}},
    ]
    should: List[Dict[str, Any]] = []

    if event_ids:
        must.append({"terms": {f"{EVENT_ID}.keyword": event_ids}})

    if topic:
        should.append({"match": {TOPIC_NAME: {"query": topic, "boost": 3}}})

    if audience_level == AUDIENCE_C_LEVEL:
        should.append({"term": {ACT_IS_CLEVEL: {"value": True, "boost": 2}}})

    query: Dict[str, Any] = {"bool": {"must": must}}
    if should:
        query["bool"]["should"] = should
        if not event_ids:
            query["bool"]["minimum_should_match"] = 1

    return query


def _extract_presenters_from_hits(
    hits: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    Aggregate presenters from activity hits. Iterates the topic_presenter array
    per activity and skips declined entries.
    """
    presenters: Dict[str, Dict[str, Any]] = {}

    for hit in hits:
        src = hit.get("source", {})
        activity_info = src.get("activityInfo") or {}
        presenter_entries = activity_info.get("topic_presenter") or []
        topic_entries = activity_info.get("topic") or []

        # Collect topic names for this activity
        topic_names: List[str] = []
        for t in topic_entries:
            name = _deep_get(t, "data.topic.textField1")
            if name and name not in topic_names:
                topic_names.append(name)
        primary_topic = topic_names[0] if topic_names else ""

        # Did this activity have a C-level audience? Field is on
        # activityInfo.EVENTS_VISIT_INFO[].data.isCLevelAttendee (array).
        visit_infos = activity_info.get("EVENTS_VISIT_INFO") or []
        is_c_level_audience = any(
            bool(_deep_get(v, "data.isCLevelAttendee")) for v in visit_infos
        )

        eid = src.get("eventId") or ""
        ts = _deep_get(src, START_TIME) or 0

        for p_entry in presenter_entries:
            p_data = p_entry.get("data") or {}
            presenter = p_data.get("presenter") or {}
            status = (p_data.get("presenterStatus") or "").strip().lower()

            if status in _EXCLUDED_STATUSES:
                continue

            first = (presenter.get("firstName") or "").strip()
            last = (presenter.get("lastName") or "").strip()
            full_name = f"{first} {last}".strip()
            email = (presenter.get("primaryEmail") or p_data.get("presenterEmail") or "").strip()
            title = (presenter.get("designation") or p_data.get("presenterTitle") or "").strip()

            if not full_name and not email:
                continue

            key = email.lower() or full_name.lower()
            if key not in presenters:
                presenters[key] = {
                    "presenter_name": full_name or email,
                    "email": email,
                    "title": title,
                    "session_count": 0,
                    "event_ids": set(),
                    "topics": [],
                    "latest_ts": 0,
                    "sample_topic": "",
                    "sample_event_id": "",
                    "accepted_count": 0,
                    "c_level_session_count": 0,
                    "seniority_tier": _presenter_seniority(title),
                }

            entry = presenters[key]
            entry["session_count"] += 1
            if status == "accepted":
                entry["accepted_count"] += 1
            if is_c_level_audience:
                entry["c_level_session_count"] += 1
            if eid:
                entry["event_ids"].add(eid)
            for tn in topic_names:
                if tn not in entry["topics"]:
                    entry["topics"].append(tn)
            if isinstance(ts, (int, float)) and ts > entry["latest_ts"]:
                entry["latest_ts"] = ts
                entry["sample_topic"] = primary_topic
                entry["sample_event_id"] = eid
            if not entry["title"] and title:
                entry["title"] = title
                entry["seniority_tier"] = _presenter_seniority(title)
            if not entry["email"] and email:
                entry["email"] = email

    return presenters


def _rank_presenters(
    presenters: Dict[str, Dict[str, Any]],
    limit: int,
    audience_level: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Rank presenters.

    Default order: accepted → total sessions → event coverage → recency.
    When audience_level is set, seniority match + C-level track record take
    priority so the top results are peers of the target audience.
    """
    min_tier = _min_seniority_for_audience(audience_level)

    def sort_key(p: Dict[str, Any]):
        if audience_level:
            meets_tier = 1 if p["seniority_tier"] >= min_tier else 0
            return (
                -meets_tier,
                -p["c_level_session_count"] if audience_level == AUDIENCE_C_LEVEL else 0,
                -p["seniority_tier"],
                -p["accepted_count"],
                -p["session_count"],
                -len(p["event_ids"]),
                -p["latest_ts"],
            )
        return (
            -p["accepted_count"],
            -p["session_count"],
            -len(p["event_ids"]),
            -p["latest_ts"],
        )

    ranked = sorted(presenters.values(), key=sort_key)

    results = []
    for p in ranked[:limit]:
        topics_summary = ", ".join(p["topics"][:3])
        if len(p["topics"]) > 3:
            topics_summary += f" (+{len(p['topics']) - 3} more)"
        reason_parts = [f"{p['session_count']} session(s)"]
        if p["accepted_count"]:
            reason_parts.append(f"{p['accepted_count']} accepted")
        if audience_level and p["c_level_session_count"]:
            reason_parts.append(f"{p['c_level_session_count']} C-level audience")
        if audience_level and p["seniority_tier"] >= min_tier and p["title"]:
            reason_parts.append(f"peer-level ({p['title']})")
        if topics_summary:
            reason_parts.append(f"on: {topics_summary}")
        results.append(
            {
                "presenter_name": p["presenter_name"],
                "email": p["email"],
                "title": p["title"],
                "session_count": p["session_count"],
                "event_count": len(p["event_ids"]),
                "c_level_session_count": p["c_level_session_count"],
                "seniority_tier": p["seniority_tier"],
                "sample_topic": p["sample_topic"],
                "sample_event_id": p["sample_event_id"],
                "sample_event_name": "",
                "reason": " | ".join(reason_parts),
            }
        )
    return results


def get_suggested_presenters(
    topic: Optional[str] = None,
    industry: Optional[str] = None,
    customer_name: Optional[str] = None,
    event_id: Optional[str] = None,
    audience_level: Optional[str] = None,
    limit: int = 10,
    index: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Query OpenSearch for presenters matching the given filters.

    Flow:
    1. If customer_name or industry, resolve them to a list of event_ids
       via the events index.
    2. Query the activities index filtered by those event_ids and/or topic.
       If audience_level is set, boost activities with a matching audience.
    3. Aggregate presenters across matching activities, rank using audience
       seniority when requested, return top N.

    audience_level values:
      - "c_level"  → prefer presenters with C-suite/Chief/President titles
      - "vp_plus"  → prefer VP+ titles
      - "senior"   → prefer Director+ titles
    """
    try:
        from opensearch_client import search
    except ImportError:
        return {
            "success": False,
            "error": "OpenSearch client not available",
            "suggested_presenters": [],
        }

    if audience_level and audience_level not in _AUDIENCE_LEVELS:
        return {
            "success": False,
            "error": f"Invalid audience_level '{audience_level}'. Expected one of: {sorted(_AUDIENCE_LEVELS)}",
            "suggested_presenters": [],
        }

    if not any([topic, industry, customer_name, event_id]):
        return {
            "success": False,
            "error": "At least one filter required: topic, industry, customer_name, or event_id",
            "suggested_presenters": [],
        }

    # Resolve event_ids from customer/industry scope (if not already given)
    scoped_event_ids: List[str] = []
    if event_id:
        scoped_event_ids = [event_id]
    elif customer_name or industry:
        scoped_event_ids = _fetch_event_ids_by_scope(customer_name, industry)
        if not scoped_event_ids:
            return {
                "success": True,
                "suggested_presenters": [],
                "message": "No matching events found for customer/industry scope",
            }

    # Need at least one constraint on activities (event_ids OR topic)
    if not scoped_event_ids and not topic:
        return {
            "success": True,
            "suggested_presenters": [],
            "message": "No activity constraint could be derived",
        }

    query = _build_activity_query(
        topic=topic,
        event_ids=scoped_event_ids or None,
        audience_level=audience_level,
    )

    body = {
        "query": query,
        "size": 100,
        "sort": [{START_TIME: {"order": "desc", "unmapped_type": "long"}}],
    }

    target_index = index or ACTIVITIES_INDEX
    logger.info(
        f"Presenter search: topic={topic}, industry={industry}, "
        f"customer={customer_name}, event_id={event_id}, scoped_events={len(scoped_event_ids)}"
    )

    result = search(index=target_index, body=body)

    if not result.get("success"):
        return {
            "success": False,
            "error": result.get("error", "Search failed"),
            "suggested_presenters": [],
        }

    hits = result.get("hits", [])
    logger.info(f"Presenter search returned {len(hits)} activity hits")

    if not hits and (customer_name or industry or event_id):
        logger.info("Scoped search returned 0 — falling back to top presenters overall")
        fallback_body = {
            "query": {"exists": {"field": PRESENTER_EMAIL_FIELD}},
            "size": 200,
            "sort": [{START_TIME: {"order": "desc", "unmapped_type": "long"}}],
        }
        fb_result = search(index=target_index, body=fallback_body)
        if fb_result.get("success"):
            hits = fb_result.get("hits", [])
            logger.info(f"Fallback search returned {len(hits)} activity hits")

    if not hits:
        return {
            "success": True,
            "suggested_presenters": [],
            "message": "No matching activities with presenters found",
        }

    presenters = _extract_presenters_from_hits(hits)
    ranked = _rank_presenters(presenters, limit, audience_level=audience_level)

    logger.info(
        f"Found {len(ranked)} unique presenters from {len(hits)} activities"
        + (f" (audience_level={audience_level})" if audience_level else "")
    )

    return {
        "success": True,
        "suggested_presenters": ranked,
        "total_activities_matched": result.get("total_hits", len(hits)),
        "audience_level": audience_level,
    }
