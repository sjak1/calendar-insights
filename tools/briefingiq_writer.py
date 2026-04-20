"""
BriefingIQ Write Client — push AI-generated agenda sessions and manage
room scheduling against the BriefingIQ REST API.

Auth + tenant context (customerId, categoryId, eventId, timezones) come from
the incoming request headers. Form template IDs are still per-location and
default to Redwood Shores — lift to a config map when onboarding a second site.

Flows:
  Agenda push (per session):
    1. POST /api/activities          → create time slot → activityId
    2. PUT  /api/forms/{TOPIC_FORM}/data/{activityId} → set topic
    3. POST /api/forms/{PRESENTER_FORM}/data          → add presenter (optional)

  Room scheduling:
    - list_rooms(headers)                              → GET /resourcetypes/{ROOM_TYPE}/resources
    - get_resource_schedule(resource_id, headers)      → GET /resources/{id}/calendars
    - find_vacant_slots(resource_id, date, ..., hdrs)  → computed from schedule
    - block_calendar(resource_id, start, end, hdrs)    → POST /resources/{id}/calendars
"""

import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests

from logging_config import get_logger

logger = get_logger(__name__)

# ── BriefingIQ constants (Redwood Shores defaults for form templates) ────────
BASE_URL          = "https://briefings.briefingiq.com/events/api"
MODULE_ID         = "BFF04CFD-87A4-4CDA-9B76-612A82C8FE5C"
TOPIC_FORM_ID     = "5622B58C-55BA-4473-9B3A-38D732DDD04B"
PRESENTER_FORM_ID = "ACED1483-82F1-4E30-B4C3-2259338B4EAE"
MASTERS_TYPE_ID   = "B147B2E9-053D-44F9-85F5-914B9F817FEA"
ROOM_TYPE_ID      = "EAC8F953-99D0-43DF-8E15-CA03F21EA92D"

# Fallback tenant IDs — only used when request headers are missing them.
CUSTOMER_ID       = "131393dd-0449-4cca-8528-2fed6b79eaed"
CATEGORY_ID       = "D06189A1-69AF-4D17-AC5B-480F7589D427"

# Cache topics for the process lifetime
_topics_cache: Optional[List[Dict]] = None
_topics_cache_ts: float = 0
_TOPICS_TTL = 3600  # 1 hour


# ── Helpers ──────────────────────────────────────────────────────────────────

def _hget(headers: Optional[Dict], *keys: str, default: Optional[str] = None) -> Optional[str]:
    """Case-tolerant header lookup — try each key in order."""
    if not headers:
        return default
    for k in keys:
        v = headers.get(k)
        if v:
            return v
    return default


def _make_headers(
    token: str,
    event_id: Optional[str] = None,
    schedule_headers: Optional[Dict] = None,
) -> Dict[str, str]:
    """
    Build headers for BriefingIQ API calls.

    Pulls customerId/categoryId/timezones/user from the incoming request headers
    when available, falls back to Redwood Shores constants otherwise.
    """
    sh = schedule_headers or {}

    customer_id = _hget(sh, "x-cloud-customerid", "x-cloud-customer-id") or CUSTOMER_ID
    category_id = _hget(sh, "x-cloud-categoryid", "x-cloud-category-id") or CATEGORY_ID
    category_type = _hget(sh, "x-cloud-categorytypeid", "x-cloud-category-type-id") or "CATEGORY_TYPE_BRIEFINGS"
    ctx_tz = _hget(sh, "x-cloud-context-timezone") or "America/Los_Angeles"
    req_tz = _hget(sh, "x-cloud-requested-timezone") or ctx_tz
    client_tz = _hget(sh, "x-cloud-client-timezone") or ctx_tz
    user_email = _hget(sh, "x_cloud_user", "x-cloud-user") or "supportuser@allianceit.com"

    # event_id arg wins, else fall back to request header
    eid = event_id or _hget(sh, "x-cloud-eventid", "x-cloud-event-id") or ""

    return {
        "Authorization": token if token.startswith("Bearer ") else f"Bearer {token}",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "x-cloud-eventid": eid,
        "x-cloud-customerid": customer_id,
        "x-cloud-categoryid": category_id,
        "x-cloud-categorytypeid": category_type,
        "x-cloud-context-timezone": ctx_tz,
        "x-cloud-requested-timezone": req_tz,
        "x-cloud-client-timezone": client_tz,
        "x_cloud_user": user_email,
        "Referer": "https://briefings.briefingiq.com/events/",
    }


def _create_topic(headers: Dict[str, str], name: str) -> Optional[Dict]:
    """Create a new topic in the masters catalogue. Returns {name, uniqueId} or None."""
    url = f"{BASE_URL}/mastertypes/{MASTERS_TYPE_ID}/masters"
    body = {"data": {"textField1": name, "textField2": name, "isActive": True}}
    resp = requests.post(url, headers=headers, json=body, timeout=30)
    if resp.status_code not in (200, 201):
        logger.error(f"Failed to create topic '{name}': {resp.status_code}: {resp.text[:200]}")
        return None
    uid = resp.json().get("uniqueId")
    if not uid:
        return None
    logger.info(f"Created new topic '{name}' → {uid}")
    # Invalidate cache so next fetch includes the new topic
    global _topics_cache_ts
    _topics_cache_ts = 0
    return {"name": name, "uniqueId": uid}


def _fetch_topics(headers: Dict[str, str]) -> List[Dict]:
    """Fetch master topic catalogue (cached)."""
    global _topics_cache, _topics_cache_ts
    if _topics_cache and (time.time() - _topics_cache_ts) < _TOPICS_TTL:
        return _topics_cache

    url = f"{BASE_URL}/mastertypes/{MASTERS_TYPE_ID}/masters"
    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code != 200:
        logger.warning(f"Failed to fetch topics: {resp.status_code}")
        return []

    masters = resp.json().get("_embedded", {}).get("masters", [])
    topics = [
        {"name": m["data"]["textField1"], "uniqueId": m["uniqueId"]}
        for m in masters
        if m.get("masterType", {}).get("name") == "Topic"
    ]
    _topics_cache = topics
    _topics_cache_ts = time.time()
    logger.info(f"Loaded {len(topics)} topics from masters")
    return topics


def _fuzzy_match_topic(title: str, topics: List[Dict]) -> Optional[Dict]:
    """Find best matching topic from masters by fuzzy word overlap."""
    if not topics:
        return None

    STOP_WORDS = {"and", "or", "the", "a", "an", "to", "for", "of", "in", "on", "with", "is", "at", "by", "from", "as", "into", "its"}
    title_words = set(re.sub(r"[^a-z0-9 ]", "", title.lower()).split()) - STOP_WORDS

    if not title_words:
        return None

    best, best_score, best_ratio = None, 0, 0.0
    for t in topics:
        topic_words = set(re.sub(r"[^a-z0-9 ]", "", t["name"].lower()).split()) - STOP_WORDS
        if not topic_words:
            continue
        # Exact match gets bonus
        if t["name"].lower() == title.lower():
            return t
        overlap = len(title_words & topic_words)
        # Ratio = overlap relative to the smaller set (so short topic names can still match)
        ratio = overlap / min(len(title_words), len(topic_words)) if overlap else 0
        if overlap > best_score or (overlap == best_score and ratio > best_ratio):
            best_score = overlap
            best_ratio = ratio
            best = t

    # Require at least 2 meaningful words overlap, or 1 word if it covers ≥50% of the topic
    if best_score >= 2:
        return best
    if best_score == 1 and best_ratio >= 0.5:
        return best
    logger.info(f"No good topic match for '{title}' (best: '{best['name'] if best else 'none'}', score: {best_score}, ratio: {best_ratio:.2f})")
    return None


def _parse_time_slot(time_slot: str, event_date: str) -> Tuple[str, str, int]:
    """
    Parse '10:00 AM - 10:45 AM' + '2026-03-02' into
    (start_iso, end_iso, duration_minutes).
    """
    parts = [p.strip() for p in time_slot.split("-")]
    if len(parts) < 2:
        # Fallback: 30 min from start if unparseable
        start = f"{event_date}T09:00:00"
        end = f"{event_date}T09:30:00"
        return start, end, 30

    def to_24h(t: str) -> str:
        t = t.strip()
        try:
            dt = datetime.strptime(t, "%I:%M %p")
        except ValueError:
            try:
                dt = datetime.strptime(t, "%I %p")
            except ValueError:
                return "09:00"
        return dt.strftime("%H:%M")

    start_24 = to_24h(parts[0])
    end_24 = to_24h(parts[1])

    start_iso = f"{event_date}T{start_24}:00"
    end_iso = f"{event_date}T{end_24}:00"

    # Duration
    fmt = "%H:%M"
    try:
        s = datetime.strptime(start_24, fmt)
        e = datetime.strptime(end_24, fmt)
        duration = int((e - s).total_seconds() / 60)
        if duration <= 0:
            duration = 30
    except Exception:
        duration = 30

    return start_iso, end_iso, duration


# ── Core steps ───────────────────────────────────────────────────────────────

def _create_activity(headers: Dict, event_id: str, event_date: str, start_iso: str, end_iso: str, duration: int, resource_id: Optional[str] = None) -> Optional[str]:
    """Step 1: Create time slot. Returns activityId or None."""
    date_iso = f"{event_date}T00:00:00"
    body = {
        "startTime": {"isoDate": start_iso},
        "endTime": {"isoDate": end_iso},
        "activityDate": {"isoDate": date_iso},
        "duration": duration,
        "activityType": "Topic",
        "source": "RC",
        "moduleId": MODULE_ID,
        "eventId": event_id,
        "recurrence": False,
        "sendInvite": False,
    }
    if resource_id:
        body["resourceId"] = resource_id
    resp = requests.post(f"{BASE_URL}/activities", headers=headers, json=body, timeout=30)
    if resp.status_code not in (200, 201):
        logger.error(f"Create activity failed {resp.status_code}: {resp.text[:200]}")
        return None
    data = resp.json()
    activity_id = data.get("activityId") or data.get("id") or data.get("uniqueId")
    logger.info(f"Created activity {activity_id} ({start_iso} → {end_iso}, {duration}min)")
    return activity_id


def _set_topic(headers: Dict, activity_id: str, topic: Dict) -> bool:
    """Step 2: Set topic on activity via PUT."""
    topic_payload = {
        "uniqueId": topic["uniqueId"],
        "textField1": topic["name"],
        "textField2": topic["name"],
    }
    body = {
        "moduleId": MODULE_ID,
        "formId": TOPIC_FORM_ID,
        "id": activity_id,
        "formTypeId": "TOPIC_ACTIVITY",
        "data": {
            "textField1": topic_payload,
            "topic": topic_payload,
        },
    }
    url = f"{BASE_URL}/forms/{TOPIC_FORM_ID}/data/{activity_id}"
    resp = requests.put(url, headers=headers, json=body, timeout=30)
    if resp.status_code not in (200, 201):
        logger.error(f"Set topic failed {resp.status_code}: {resp.text[:200]}")
        return False
    logger.info(f"Set topic '{topic['name']}' on activity {activity_id}")
    return True


def _add_presenter(headers: Dict, activity_id: str, presenter_email: str, presenter_title: str = "") -> bool:
    """Step 3: Add a presenter to an activity (optional)."""
    body = {
        "formId": PRESENTER_FORM_ID,
        "moduleId": MODULE_ID,
        "parentId": activity_id,
        "data": {
            "textField2": presenter_email,
            "textField3": presenter_title,
            "textField1": "Accepted",
        },
    }
    url = f"{BASE_URL}/forms/{PRESENTER_FORM_ID}/data"
    resp = requests.post(url, headers=headers, json=body, timeout=30)
    if resp.status_code not in (200, 201):
        logger.warning(f"Add presenter failed {resp.status_code}: {resp.text[:200]}")
        return False
    logger.info(f"Added presenter {presenter_email} to activity {activity_id}")
    return True


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_event_rooms(event_id: str, token: str, schedule_headers: Optional[Dict] = None) -> List[Dict]:
    """
    Fetch rooms assigned to an event, grouped by date.
    Returns list of dicts: {name, resource_id, date}.
    """
    headers = _make_headers(token, event_id, schedule_headers)
    url = f"{BASE_URL}/events/{event_id}/eventresources"
    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code != 200:
        logger.warning(f"Failed to fetch event resources: {resp.status_code}")
        return []

    rooms = []
    event_dates = resp.json().get("_embedded", {}).get("eventDates", [])
    for ed in event_dates:
        date_str = ed.get("eventDate", {}).get("client", {}).get("clientZoneDate", "")[:10]
        for res in ed.get("resources", []):
            resource_id = res.get("resourceId")
            name = res.get("resource", {}).get("data", {}).get("name") or \
                   res.get("resource", {}).get("metaData", {}).get("searchDisplayText", "")
            if resource_id and name:
                rooms.append({"name": name, "resource_id": resource_id, "date": date_str})
    logger.info(f"Fetched {len(rooms)} rooms for event {event_id}")
    return rooms


def push_agenda_to_app(
    event_id: str,
    event_date: str,
    sessions: List[Dict[str, Any]],
    token: str,
    presenter_emails: Optional[List[str]] = None,
    resource_id: Optional[str] = None,
    schedule_headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Push AI-generated agenda sessions into the BriefingIQ app.

    Args:
        event_id:        BriefingIQ event UUID
        event_date:      Date string "YYYY-MM-DD" (start date of event)
        sessions:        List of session dicts from generate_agenda output
                         Each must have 'time_slot' and 'title'.
        token:           Bearer token from request headers
        presenter_emails: Optional list of presenter emails to add to every session
        resource_id:     Optional room resourceId to assign activities to (shows in calendar)
        schedule_headers: Incoming request headers (used for tenant/category context)

    Returns:
        Dict with success count, failures, and created activity IDs
    """
    headers = _make_headers(token, event_id, schedule_headers)
    topics = _fetch_topics(headers)

    # ── Pre-flight: check room conflicts if a room is specified ──────────
    conflicts = []
    existing_bookings: List[Dict] = []
    if resource_id:
        existing_bookings = get_resource_schedule(resource_id, token, schedule_headers, event_id=event_id)
        logger.info(f"push_agenda_to_app: {len(existing_bookings)} existing bookings on room {resource_id}")

    def _iso_to_ms(iso_str: str) -> int:
        """Convert local ISO string (YYYY-MM-DDTHH:MM:SS) to epoch ms using request tz."""
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            ZoneInfo = None  # type: ignore
        sh = schedule_headers or {}
        tz_name = _hget(sh, "x-cloud-requested-timezone", "x-cloud-context-timezone") or "America/Los_Angeles"
        dt = datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%S")
        if ZoneInfo:
            dt = dt.replace(tzinfo=ZoneInfo(tz_name))
        return int(dt.timestamp() * 1000)

    def _overlaps(s1_ms: int, e1_ms: int, s2_ms: int, e2_ms: int) -> bool:
        return s1_ms < e2_ms and s2_ms < e1_ms

    if resource_id and existing_bookings:
        for i, session in enumerate(sessions):
            time_slot = session.get("time_slot", "")
            start_iso, end_iso, _ = _parse_time_slot(time_slot, event_date)
            s_ms = _iso_to_ms(start_iso)
            e_ms = _iso_to_ms(end_iso)
            for bk in existing_bookings:
                if _overlaps(s_ms, e_ms, bk["start_utc_ms"], bk["end_utc_ms"]):
                    conflicts.append({
                        "session": session.get("title") or session.get("name") or f"Session {i+1}",
                        "session_slot": time_slot,
                        "conflicting_booking": bk.get("comments") or bk.get("kind", "BLOCKED"),
                        "conflicting_kind": bk.get("kind", "BLOCKED"),
                        "conflicting_start_utc_ms": bk["start_utc_ms"],
                        "conflicting_end_utc_ms": bk["end_utc_ms"],
                    })
                    break

    if conflicts:
        logger.warning(f"push_agenda_to_app: {len(conflicts)} conflict(s) detected, aborting push")
        return {
            "success": False,
            "event_id": event_id,
            "status": "conflicts",
            "conflicts": conflicts,
            "message": f"{len(conflicts)} session(s) overlap with existing bookings on this room. Resolve conflicts before pushing.",
        }

    # ── Push sessions ────────────────────────────────────────────────────
    created = []
    failed = []

    for i, session in enumerate(sessions):
        title = session.get("title") or session.get("name") or f"Session {i+1}"
        time_slot = session.get("time_slot", "")

        # Parse time
        start_iso, end_iso, duration = _parse_time_slot(time_slot, event_date)

        # Step 1: create activity (with optional room assignment)
        activity_id = _create_activity(headers, event_id, event_date, start_iso, end_iso, duration, resource_id=resource_id)
        if not activity_id:
            failed.append({"session": title, "reason": "failed to create activity"})
            continue

        # Step 2: match or create topic, then set it
        matched_topic = _fuzzy_match_topic(title, topics)
        if not matched_topic:
            matched_topic = _create_topic(headers, title)
        if matched_topic:
            _set_topic(headers, activity_id, matched_topic)
        else:
            logger.warning(f"Could not match or create topic for '{title}' — activity created without topic")

        # Step 3: add presenters if provided
        if presenter_emails:
            for email in presenter_emails:
                _add_presenter(headers, activity_id, email)

        created.append({
            "activity_id": activity_id,
            "title": title,
            "time_slot": time_slot,
            "matched_topic": matched_topic["name"] if matched_topic else None,
            "resource_id": resource_id,
        })

    result = {
        "success": True,
        "event_id": event_id,
        "created_count": len(created),
        "failed_count": len(failed),
        "created": created,
        "failed": failed,
    }
    logger.info(f"push_agenda_to_app: {len(created)} created, {len(failed)} failed for event {event_id}")
    return result


# ── Room scheduling ──────────────────────────────────────────────────────────

def list_rooms(token: str, schedule_headers: Optional[Dict] = None, event_id: Optional[str] = None) -> List[Dict]:
    """
    Smart room listing: event rooms first, tenant rooms as fallback.

    If *event_id* is provided (or present in schedule_headers), fetch rooms
    assigned to that event via ``/events/{id}/eventresources``.  These are the
    rooms visible on the event calendar (Horizon Chamber, Panorama Suite, …).

    When no event context exists, fall back to the tenant-wide room pool via
    ``/resourcetypes/{ROOM_TYPE}/resources?fetchType=HIERARCHY_LEVEL``
    (Outlook 1-6, Executive Lounge, …).

    Returns [{resource_id, name, capacity?, date?, source}].
    """
    # Resolve event_id: explicit arg > header
    eid = event_id or _hget(schedule_headers or {}, "x-cloud-eventid", "x-cloud-event-id") or ""

    # ── Try event-level rooms first ──────────────────────────────────────
    if eid:
        event_rooms = fetch_event_rooms(eid, token, schedule_headers)
        if event_rooms:
            # Deduplicate by resource_id (same room may appear on multiple dates)
            seen = {}
            for r in event_rooms:
                rid = r["resource_id"]
                if rid not in seen:
                    seen[rid] = {
                        "resource_id": rid,
                        "name": r["name"],
                        "dates": [r["date"]],
                        "source": "event",
                    }
                else:
                    if r["date"] not in seen[rid]["dates"]:
                        seen[rid]["dates"].append(r["date"])
            rooms = list(seen.values())
            logger.info(f"list_rooms: {len(rooms)} event-level rooms for event {eid}")
            return rooms
        logger.info(f"list_rooms: no event rooms for {eid}, falling back to tenant pool")

    # ── Fallback: tenant-wide room pool ──────────────────────────────────
    headers = _make_headers(token, None, schedule_headers)
    url = f"{BASE_URL}/resourcetypes/{ROOM_TYPE_ID}/resources?fetchType=HIERARCHY_LEVEL"
    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code != 200:
        logger.warning(f"list_rooms failed {resp.status_code}: {resp.text[:200]}")
        return []

    items = resp.json().get("_embedded", {}).get("resources", [])
    rooms = []
    for it in items:
        data = it.get("data", {}) or {}
        if data.get("isActive") is False:
            continue
        rooms.append({
            "resource_id": it.get("uniqueId"),
            "name": data.get("name") or data.get("textField1") or it.get("metaData", {}).get("searchDisplayText", ""),
            "capacity": data.get("capacity"),
            "source": "tenant",
        })
    logger.info(f"list_rooms: returned {len(rooms)} tenant rooms")
    return rooms


def list_event_activities(
    token: str,
    schedule_headers: Optional[Dict] = None,
    event_id: Optional[str] = None,
    date: Optional[str] = None,
) -> List[Dict]:
    """
    List every activity on an event (optionally narrowed to a single date).

    Hits ``/activities?view=list`` which — unlike ``view=calendar`` — returns
    full resource info on each timeslot. Groups nothing; the caller / LLM can
    format.

    Args:
        date: YYYY-MM-DD in the request timezone. If omitted, returns a
              ±6-month window around now (whole event).

    Returns [{activity_id, title, activity_type, booking_id, start_utc_ms,
              end_utc_ms, start_iso, end_iso, room_id, room_name, status}].
    """
    eid = event_id or _hget(schedule_headers or {}, "x-cloud-eventid", "x-cloud-event-id") or ""
    if not eid:
        logger.warning("list_event_activities: no event_id in args or headers")
        return []

    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        ZoneInfo = None  # type: ignore

    sh = schedule_headers or {}
    tz_name = _hget(sh, "x-cloud-requested-timezone", "x-cloud-context-timezone") or "America/Los_Angeles"
    tz = ZoneInfo(tz_name) if ZoneInfo else None

    if date:
        base = datetime.strptime(date, "%Y-%m-%d")
        day_start = base.replace(hour=0, minute=0, second=0)
        day_end = base.replace(hour=23, minute=59, second=59)
        if tz:
            day_start = day_start.replace(tzinfo=tz)
            day_end = day_end.replace(tzinfo=tz)
        s_ms = int(day_start.timestamp() * 1000)
        e_ms = int(day_end.timestamp() * 1000)
    else:
        now_ms = int(time.time() * 1000)
        six_months = 6 * 30 * 24 * 3600 * 1000
        s_ms = now_ms - six_months
        e_ms = now_ms + six_months

    headers = _make_headers(token, eid, schedule_headers)
    url = f"{BASE_URL}/activities?view=list&startDate={s_ms}&endDate={e_ms}"
    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code != 200:
        logger.warning(f"list_event_activities failed {resp.status_code}: {resp.text[:200]}")
        return []

    items = resp.json().get("_embedded", {}).get("resourceTimeSlots", []) or []
    out = []
    for it in items:
        st = (it.get("startTime") or {}).get("utcMs")
        et = (it.get("endTime") or {}).get("utcMs")
        if st is None or et is None:
            continue
        r = it.get("resource") or {}
        room_id = r.get("uniqueId") or ""
        room_name = (r.get("metaData") or {}).get("searchDisplayText") or r.get("name") or ""
        fd = (it.get("formData") or {}).get("data") or {}
        title = (
            (fd.get("name") if isinstance(fd, dict) else None)
            or (fd.get("textField1") if isinstance(fd, dict) else None)
            or it.get("activityType")
            or it.get("bookingId")
            or "Activity"
        )
        out.append({
            "activity_id": it.get("activityId"),
            "title": title,
            "activity_type": it.get("activityType"),
            "booking_id": it.get("bookingId"),
            "start_utc_ms": st,
            "end_utc_ms": et,
            "start_iso": (it.get("startTime") or {}).get("zoneTime"),
            "end_iso": (it.get("endTime") or {}).get("zoneTime"),
            "date": ((it.get("startTime") or {}).get("client") or {}).get("clientZoneDate", "")[:10],
            "room_id": room_id,
            "room_name": room_name,
            "status": (it.get("status") or {}).get("displayText"),
        })
    out.sort(key=lambda x: x["start_utc_ms"])
    logger.info(f"list_event_activities: {len(out)} activities for event {eid} (date={date or 'all'})")
    return out


def get_resource_schedule(
    resource_id: str,
    token: str,
    schedule_headers: Optional[Dict] = None,
    event_id: Optional[str] = None,
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
) -> List[Dict]:
    """
    Fetch existing bookings on a resource (room).

    Merges two sources:
      1. Event activities — GET /activities?view=list (filtered client-side to this room)
      2. Blocked holds    — GET /resources/{id}/calendars (tenant-wide blocks)

    The list endpoint requires an event_id + date window; defaults to a ±6 month
    window around now if not supplied. event_id is pulled from schedule_headers
    if not passed explicitly.

    Returns [{unique_id, kind, start_utc_ms, end_utc_ms, comments}] sorted by start.
    `kind` is "ACTIVITY" or "BLOCKED".
    """
    out: List[Dict] = []

    # ── Source 1: event activities via /activities?view=list ─────────────
    eid = event_id or _hget(schedule_headers or {}, "x-cloud-eventid", "x-cloud-event-id") or ""
    if eid:
        headers = _make_headers(token, eid, schedule_headers)
        now_ms = int(time.time() * 1000)
        six_months = 6 * 30 * 24 * 3600 * 1000
        s_ms = start_ms if start_ms is not None else now_ms - six_months
        e_ms = end_ms if end_ms is not None else now_ms + six_months
        url = f"{BASE_URL}/activities?view=list&startDate={s_ms}&endDate={e_ms}"
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            items = resp.json().get("_embedded", {}).get("resourceTimeSlots", []) or []
            for it in items:
                r = it.get("resource") or {}
                rids = [r.get("uniqueId")] if r.get("uniqueId") else []
                rids += [rr.get("uniqueId") for rr in (it.get("resources") or []) if rr.get("uniqueId")]
                if resource_id not in rids:
                    continue
                st = (it.get("startTime") or {}).get("utcMs")
                et = (it.get("endTime") or {}).get("utcMs")
                if st is None or et is None:
                    continue
                # Activity title lives in formData.data — often empty in list view;
                # fall back to activityType/bookingId so the conflict message is informative.
                fd = (it.get("formData") or {}).get("data") or {}
                title = (
                    fd.get("name") if isinstance(fd, dict) else None
                ) or (fd.get("textField1") if isinstance(fd, dict) else None) \
                    or it.get("activityType") \
                    or it.get("bookingId") \
                    or "Activity"
                out.append({
                    "unique_id": it.get("activityId"),
                    "kind": "ACTIVITY",
                    "start_utc_ms": st,
                    "end_utc_ms": et,
                    "comments": title,
                })
        else:
            logger.warning(f"get_resource_schedule /activities failed {resp.status_code}: {resp.text[:200]}")

    # ── Source 2: blocked calendar entries via /resources/{id}/calendars ──
    headers = _make_headers(token, None, schedule_headers)
    url = f"{BASE_URL}/resources/{resource_id}/calendars"
    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code == 200:
        entries = resp.json().get("_embedded", {}).get("resourceCalendars", []) or []
        for e in entries:
            st = (e.get("calendarStartTime") or {}).get("utcMs")
            et = (e.get("calendarEndTime") or {}).get("utcMs")
            if st is None or et is None:
                continue
            out.append({
                "unique_id": e.get("uniqueId"),
                "kind": e.get("calendarType") or "BLOCKED",
                "start_utc_ms": st,
                "end_utc_ms": et,
                "comments": e.get("comments"),
            })
    else:
        logger.warning(f"get_resource_schedule /calendars failed {resp.status_code}: {resp.text[:200]}")

    out.sort(key=lambda x: x["start_utc_ms"])
    logger.info(f"get_resource_schedule: {len(out)} entries for room {resource_id} (event={eid or 'none'})")
    return out


def find_vacant_slots(
    resource_id: str,
    date: str,
    duration_minutes: int,
    token: str,
    schedule_headers: Optional[Dict] = None,
    day_start_hour: int = 9,
    day_end_hour: int = 18,
) -> List[Dict]:
    """
    Compute free windows of at least `duration_minutes` on `date` for a room.

    Args:
        date: YYYY-MM-DD
        day_start_hour / day_end_hour: working-hours bounds (local tz from headers)

    Returns [{start_iso, end_iso, start_utc_ms, end_utc_ms}] in the request
    timezone, using wall-clock times the caller can hand straight to block_calendar.
    """
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        ZoneInfo = None  # type: ignore

    sh = schedule_headers or {}
    tz_name = _hget(sh, "x-cloud-requested-timezone", "x-cloud-context-timezone") or "America/Los_Angeles"
    tz = ZoneInfo(tz_name) if ZoneInfo else None

    # Day bounds in the request timezone
    base = datetime.strptime(date, "%Y-%m-%d")
    day_start = base.replace(hour=day_start_hour, minute=0, second=0, microsecond=0)
    day_end = base.replace(hour=day_end_hour, minute=0, second=0, microsecond=0)
    if tz:
        day_start = day_start.replace(tzinfo=tz)
        day_end = day_end.replace(tzinfo=tz)

    day_start_ms = int(day_start.timestamp() * 1000)
    day_end_ms = int(day_end.timestamp() * 1000)

    # Existing bookings that overlap this day
    existing = get_resource_schedule(resource_id, token, schedule_headers)
    busy = [
        (max(e["start_utc_ms"], day_start_ms), min(e["end_utc_ms"], day_end_ms))
        for e in existing
        if e["end_utc_ms"] > day_start_ms and e["start_utc_ms"] < day_end_ms
    ]
    busy.sort()

    # Merge overlapping busy spans
    merged: List[Tuple[int, int]] = []
    for start, end in busy:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    # Walk through the day, emit gaps >= duration
    min_ms = duration_minutes * 60 * 1000
    free: List[Dict] = []
    cursor = day_start_ms
    for start, end in merged:
        if start - cursor >= min_ms:
            free.append({"start_utc_ms": cursor, "end_utc_ms": start})
        cursor = max(cursor, end)
    if day_end_ms - cursor >= min_ms:
        free.append({"start_utc_ms": cursor, "end_utc_ms": day_end_ms})

    # Attach wall-clock ISO strings
    for slot in free:
        s_dt = datetime.fromtimestamp(slot["start_utc_ms"] / 1000, tz=tz) if tz else datetime.utcfromtimestamp(slot["start_utc_ms"] / 1000)
        e_dt = datetime.fromtimestamp(slot["end_utc_ms"] / 1000, tz=tz) if tz else datetime.utcfromtimestamp(slot["end_utc_ms"] / 1000)
        slot["start_iso"] = s_dt.strftime("%Y-%m-%dT%H:%M:%S")
        slot["end_iso"] = e_dt.strftime("%Y-%m-%dT%H:%M:%S")

    logger.info(f"find_vacant_slots: {len(free)} slot(s) ≥{duration_minutes}min on {date} for {resource_id}")
    return free


def block_calendar(
    resource_id: str,
    start_iso: str,
    end_iso: str,
    token: str,
    schedule_headers: Optional[Dict] = None,
    comments: Optional[str] = None,
    calendar_type: str = "BLOCKED",
    skip_conflict_check: bool = False,
) -> Dict[str, Any]:
    """
    Create a calendar entry on a resource (room) with a pre-flight conflict check.

    Args:
        resource_id: Target room resource UUID (from list_rooms).
        start_iso / end_iso: Local wall-clock ISO-8601 strings (YYYY-MM-DDTHH:MM:SS).
        calendar_type: "BLOCKED" (default) or another type supported by BriefingIQ.
        skip_conflict_check: Set True to bypass overlap detection (not recommended).

    Returns {status, message, resource_id, start_iso, end_iso} or
    {status: "conflict", conflicting: [...]} if overlap detected.
    """
    # Pre-flight conflict check
    if not skip_conflict_check:
        try:
            start_dt = datetime.strptime(start_iso, "%Y-%m-%dT%H:%M:%S")
            end_dt = datetime.strptime(end_iso, "%Y-%m-%dT%H:%M:%S")
        except ValueError as e:
            return {"status": "error", "message": f"Invalid ISO datetime: {e}"}

        sh = schedule_headers or {}
        tz_name = _hget(sh, "x-cloud-requested-timezone", "x-cloud-context-timezone") or "America/Los_Angeles"
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(tz_name)
            start_ms = int(start_dt.replace(tzinfo=tz).timestamp() * 1000)
            end_ms = int(end_dt.replace(tzinfo=tz).timestamp() * 1000)
        except Exception:
            start_ms = int(start_dt.timestamp() * 1000)
            end_ms = int(end_dt.timestamp() * 1000)

        existing = get_resource_schedule(resource_id, token, schedule_headers)
        conflicts = [
            {
                "unique_id": e["unique_id"],
                "kind": e.get("kind", "BLOCKED"),
                "start_utc_ms": e["start_utc_ms"],
                "end_utc_ms": e["end_utc_ms"],
                "comments": e.get("comments"),
            }
            for e in existing
            if e["end_utc_ms"] > start_ms and e["start_utc_ms"] < end_ms
        ]
        if conflicts:
            logger.info(f"block_calendar: conflict on {resource_id} ({len(conflicts)} overlapping entries)")
            return {
                "status": "conflict",
                "resource_id": resource_id,
                "conflicting": conflicts,
                "message": f"{len(conflicts)} existing entr{'y' if len(conflicts) == 1 else 'ies'} overlap this window",
            }

    headers = _make_headers(token, None, schedule_headers)
    url = f"{BASE_URL}/resources/{resource_id}/calendars"

    # BriefingIQ expects from/to date anchors alongside start/end time
    date_prefix = start_iso.split("T", 1)[0]
    date_iso_midnight = f"{date_prefix}T00:00:00"
    body = {
        "calendarFromDate": {"isoDate": date_iso_midnight},
        "calendarStartTime": {"isoDate": start_iso},
        "calendarEndTime": {"isoDate": end_iso},
        "calendarToDate": {"isoDate": date_iso_midnight},
        "calendarType": calendar_type,
        "comments": comments,
    }

    resp = requests.post(url, headers=headers, json=body, timeout=30)
    if resp.status_code not in (200, 201):
        logger.error(f"block_calendar failed {resp.status_code}: {resp.text[:300]}")
        return {
            "status": "error",
            "http_status": resp.status_code,
            "message": resp.text[:300],
            "resource_id": resource_id,
        }

    logger.info(f"block_calendar: created entry on {resource_id} ({start_iso} → {end_iso})")
    return {
        "status": "success",
        "resource_id": resource_id,
        "start_iso": start_iso,
        "end_iso": end_iso,
        "calendar_type": calendar_type,
        "message": "Calendar entry created",
    }
