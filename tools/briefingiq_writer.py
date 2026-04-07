"""
BriefingIQ Write Client — push AI-generated agenda sessions into the app.

Flow per session:
  1. POST /api/activities          → create time slot → activityId
  2. PUT  /api/forms/{TOPIC_FORM}/data/{activityId} → set topic (fuzzy matched from masters)
  3. POST /api/forms/{PRESENTER_FORM}/data          → add presenter (optional)

Constants are hardcoded for Oracle EBC Redwood Shores.
Other locations will have different categoryId / moduleId — extend via config if needed.
"""

import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests

from logging_config import get_logger

logger = get_logger(__name__)

# ── Hardcoded Oracle EBC Redwood Shores constants ────────────────────────────
BASE_URL          = "https://briefings.briefingiq.com/events/api"
MODULE_ID         = "BFF04CFD-87A4-4CDA-9B76-612A82C8FE5C"
TOPIC_FORM_ID     = "5622B58C-55BA-4473-9B3A-38D732DDD04B"
PRESENTER_FORM_ID = "ACED1483-82F1-4E30-B4C3-2259338B4EAE"
CUSTOMER_ID       = "131393dd-0449-4cca-8528-2fed6b79eaed"
CATEGORY_ID       = "D06189A1-69AF-4D17-AC5B-480F7589D427"
MASTERS_TYPE_ID   = "B147B2E9-053D-44F9-85F5-914B9F817FEA"

# Cache topics for the process lifetime
_topics_cache: Optional[List[Dict]] = None
_topics_cache_ts: float = 0
_TOPICS_TTL = 3600  # 1 hour


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_headers(token: str, event_id: str) -> Dict[str, str]:
    return {
        "Authorization": token if token.startswith("Bearer ") else f"Bearer {token}",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "x-cloud-eventid": event_id,
        "x-cloud-customerid": CUSTOMER_ID,
        "x-cloud-categoryid": CATEGORY_ID,
        "x-cloud-categorytypeid": "CATEGORY_TYPE_BRIEFINGS",
        "x-cloud-context-timezone": "America/Los_Angeles",
        "x-cloud-requested-timezone": "America/Los_Angeles",
        "x-cloud-client-timezone": "America/Los_Angeles",
        "x_cloud_user": "supportuser@allianceit.com",
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

def fetch_event_rooms(event_id: str, token: str) -> List[Dict]:
    """
    Fetch rooms assigned to an event, grouped by date.
    Returns list of dicts: {name, resource_id, date}.
    """
    headers = _make_headers(token, event_id)
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

    Returns:
        Dict with success count, failures, and created activity IDs
    """
    headers = _make_headers(token, event_id)
    topics = _fetch_topics(headers)

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
