"""
Briefing builder — the write half of the agentic briefing flow.

Flow (strictly ordered):
  1. The agent interviews the user and gathers data (catalog / OpenSearch tools).
  2. draft_briefing(...)  → validates + assembles a complete draft, returns a
     draft_id and a human-readable summary. NO writes happen here.
  3. The agent shows the summary; the user must explicitly confirm.
  4. push_briefing(draft_id, ...) → executes the writes in order:
        a. POST /events/{eventid}/meetings                      → the briefing request
        b. POST /events/{eventid}/meetings/{mid}/{attendeetype} → attendees
        c. push_agenda_to_app(...)                              → agenda sessions (optional)
     Partial failures are reported per step; completed steps are never rolled back.

Drafts live in process memory with a TTL — a draft_id from an old session
cannot be replayed after expiry.
"""
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from logging_config import get_logger
from tools.briefingiq_writer import BASE_URL, _hget, _make_headers, push_agenda_to_app

logger = get_logger(__name__)

_DRAFTS: Dict[str, Dict[str, Any]] = {}
_DRAFT_TTL = 3600  # 1 hour — long enough for a review conversation

# Meeting-level attendee collections (path segment for {attendeetype}).
INTERNAL_ATTENDEE_TYPE = "internalattendees"
EXTERNAL_ATTENDEE_TYPE = "externalattendees"


def _now() -> float:
    return time.time()


def _prune_drafts() -> None:
    expired = [k for k, v in _DRAFTS.items() if _now() - v["created"] > _DRAFT_TTL]
    for k in expired:
        del _DRAFTS[k]


def _tz_name(schedule_headers: Optional[Dict]) -> str:
    return (
        _hget(schedule_headers or {}, "x-cloud-requested-timezone", "x-cloud-context-timezone")
        or "America/Los_Angeles"
    )


def _to_ms(date_str: str, time_str: str, tz_name: str) -> int:
    """'2026-07-20' + '10:00' (24h) → epoch ms in the request timezone."""
    dt = datetime.strptime(f"{date_str}T{time_str}", "%Y-%m-%dT%H:%M")
    try:
        from zoneinfo import ZoneInfo

        dt = dt.replace(tzinfo=ZoneInfo(tz_name))
    except ImportError:
        pass
    return int(dt.timestamp() * 1000)


def _fetch_event_locations(headers: Dict[str, str], event_id: str) -> List[Dict]:
    """Rooms attached to the event — used to resolve a room name to a uniqueId."""
    url = f"{BASE_URL}/events/{event_id}/locations"
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            logger.warning(f"event locations fetch failed: HTTP {resp.status_code}")
            return []
        data = resp.json()
        embedded = data.get("_embedded", {})
        for value in embedded.values():
            if isinstance(value, list):
                return value
        return data if isinstance(data, list) else []
    except requests.RequestException as exc:
        logger.warning(f"event locations fetch failed: {exc}")
        return []


def _location_name(loc: Dict) -> str:
    for key in ("locationName", "name", "displayName"):
        if loc.get(key):
            return str(loc[key])
    meta = loc.get("metaData") or {}
    return str(meta.get("searchDisplayText") or loc.get("uniqueId") or "")


def _resolve_room(headers: Dict, event_id: str, room_name: Optional[str]):
    """Returns (location_dict_or_None, available_names, note)."""
    locations = _fetch_event_locations(headers, event_id)
    names = [_location_name(l) for l in locations]
    if not room_name:
        return None, names, "No room requested — briefing will be created without one."
    want = room_name.lower().strip()
    for loc in locations:
        name = _location_name(loc).lower()
        if want == name or want in name or name in want:
            return loc, names, None
    return None, names, f"Room '{room_name}' not found on this event."


def draft_briefing(
    event_id: str,
    token: str,
    customer_name: str,
    briefing_date: str,
    start_time: str,
    end_time: str,
    objective: Optional[str] = None,
    room_name: Optional[str] = None,
    presenter_emails: Optional[List[str]] = None,
    internal_attendees: Optional[List[Dict]] = None,
    external_attendees: Optional[List[Dict]] = None,
    agenda_sessions: Optional[List[Dict]] = None,
    schedule_headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Validate and assemble a briefing draft. Performs read-only lookups
    (room resolution) but never writes. Returns draft_id + summary for user review.
    """
    _prune_drafts()

    missing = []
    if not event_id:
        missing.append("event_id")
    if not customer_name:
        missing.append("customer_name")
    for field, value in (("briefing_date", briefing_date), ("start_time", start_time), ("end_time", end_time)):
        if not value:
            missing.append(field)
    if missing:
        return {"success": False, "error": f"Missing required fields: {missing}"}

    tz = _tz_name(schedule_headers)
    try:
        day_ms = _to_ms(briefing_date, "00:00", tz)
        start_ms = _to_ms(briefing_date, start_time, tz)
        end_ms = _to_ms(briefing_date, end_time, tz)
    except ValueError as exc:
        return {"success": False, "error": f"Bad date/time format ({exc}). Use YYYY-MM-DD and HH:MM (24h)."}
    if end_ms <= start_ms:
        return {"success": False, "error": "end_time must be after start_time."}

    headers = _make_headers(token, event_id, schedule_headers)
    location, room_options, room_note = _resolve_room(headers, event_id, room_name)

    assumptions = []
    if room_note:
        assumptions.append(room_note)
    if not objective:
        assumptions.append("No objective provided.")
    if not (internal_attendees or external_attendees):
        assumptions.append("No attendees listed yet.")

    briefing = {
        "event_id": event_id,
        "customer_name": customer_name,
        "objective": objective or "",
        "briefing_date": briefing_date,
        "start_time": start_time,
        "end_time": end_time,
        "timezone": tz,
        "epoch": {"day_ms": day_ms, "start_ms": start_ms, "end_ms": end_ms},
        "room": {
            "name": _location_name(location) if location else None,
            "uniqueId": (location or {}).get("uniqueId"),
        },
        "presenter_emails": presenter_emails or [],
        "internal_attendees": internal_attendees or [],
        "external_attendees": external_attendees or [],
        "agenda_sessions": agenda_sessions or [],
    }

    draft_id = uuid.uuid4().hex[:12]
    _DRAFTS[draft_id] = {"created": _now(), "briefing": briefing, "pushed": False}

    def _fmt_attendee(a: Dict) -> str:
        name = f"{a.get('firstName', '')} {a.get('lastName', '')}".strip() or a.get("email", "?")
        return f"{name} ({a.get('email', 'no email')})"

    lines = [
        f"**Customer:** {customer_name}",
        f"**Objective:** {objective or '—'}",
        f"**Date:** {briefing_date}  {start_time}–{end_time} ({tz})",
        f"**Room:** {briefing['room']['name'] or '— none —'}",
        f"**Presenters:** {', '.join(presenter_emails) if presenter_emails else '—'}",
        f"**Internal attendees:** {', '.join(_fmt_attendee(a) for a in internal_attendees or []) or '—'}",
        f"**External attendees:** {', '.join(_fmt_attendee(a) for a in external_attendees or []) or '—'}",
        f"**Agenda sessions:** {len(agenda_sessions or [])}",
    ]

    return {
        "success": True,
        "draft_id": draft_id,
        "summary_markdown": "\n".join(lines),
        "briefing": briefing,
        "assumptions": assumptions,
        "room_options": room_options if (room_name and not location) else None,
        "next_step": (
            "Show this summary to the user. Only call push_briefing after they explicitly confirm."
        ),
    }


def push_briefing(
    draft_id: str,
    token: str,
    schedule_headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Execute the writes for a confirmed draft. Ordered, partial-failure tolerant.
    """
    _prune_drafts()
    entry = _DRAFTS.get(draft_id)
    if entry is None:
        return {"success": False, "error": f"Draft '{draft_id}' not found or expired. Re-run draft_briefing."}
    if entry["pushed"]:
        return {"success": False, "error": f"Draft '{draft_id}' was already pushed — refusing to push twice."}

    b = entry["briefing"]
    event_id = b["event_id"]
    headers = _make_headers(token, event_id, schedule_headers)
    steps: List[Dict[str, Any]] = []

    # ── Step 1: create the briefing request (meeting) ─────────────────────
    request_date: Dict[str, Any] = {
        "requestDate": b["epoch"]["day_ms"],
        "requestedStartTime": b["epoch"]["start_ms"],
        "requestedEndTime": b["epoch"]["end_ms"],
    }
    if b["room"]["uniqueId"]:
        request_date["location"] = {"uniqueId": b["room"]["uniqueId"]}
    payload: Dict[str, Any] = {"requestDates": [request_date]}
    if b["presenter_emails"]:
        payload["presenters"] = [{"primaryEmail": [e]} for e in b["presenter_emails"]]

    url = f"{BASE_URL}/events/{event_id}/meetings"
    logger.info(f"push_briefing {draft_id}: POST {url}")
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
    except requests.RequestException as exc:
        return {"success": False, "steps": [{"step": "create_meeting", "ok": False, "error": str(exc)}]}

    if resp.status_code != 200:
        return {
            "success": False,
            "steps": [{
                "step": "create_meeting", "ok": False,
                "error": f"HTTP {resp.status_code}", "body": resp.text[:500],
            }],
        }

    try:
        created = resp.json() if resp.text.strip() else {}
    except ValueError:
        created = {}
    meeting_id = created.get("meetingId")
    if not meeting_id:
        # Some tenants return 200 with an empty body and create nothing
        # (observed live on Customer-Briefing-Request events, where briefings
        # are events, not meetings). Surface it instead of pretending success,
        # and leave the draft pushable so a corrected flow can retry.
        return {
            "success": False,
            "steps": [{
                "step": "create_meeting", "ok": False,
                "error": (
                    f"Server returned HTTP {resp.status_code} but no meetingId "
                    "(empty response) — the briefing was NOT created. This event "
                    "type may not support meeting creation."
                ),
            }],
        }
    steps.append({
        "step": "create_meeting", "ok": True,
        "meeting_id": meeting_id, "status": created.get("status"),
    })

    # ── Step 2: attendees (meeting-level) ─────────────────────────────────
    for attendee_type, attendees in (
        (INTERNAL_ATTENDEE_TYPE, b["internal_attendees"]),
        (EXTERNAL_ATTENDEE_TYPE, b["external_attendees"]),
    ):
        for attendee in attendees:
            step_name = f"add_{attendee_type}:{attendee.get('email', '?')}"
            if not meeting_id:
                steps.append({"step": step_name, "ok": False, "error": "no meeting_id from step 1"})
                continue
            a_url = f"{BASE_URL}/events/{event_id}/meetings/{meeting_id}/{attendee_type}"
            try:
                a_resp = requests.post(a_url, headers=headers, json=attendee, timeout=30)
                ok = a_resp.status_code in (200, 201)
                step: Dict[str, Any] = {"step": step_name, "ok": ok}
                if not ok:
                    step["error"] = f"HTTP {a_resp.status_code}"
                    step["body"] = a_resp.text[:300]
                steps.append(step)
            except requests.RequestException as exc:
                steps.append({"step": step_name, "ok": False, "error": str(exc)})

    # ── Step 3: agenda sessions (optional, reuses the proven agenda push) ─
    if b["agenda_sessions"]:
        agenda_result = push_agenda_to_app(
            event_id=event_id,
            event_date=b["briefing_date"],
            sessions=b["agenda_sessions"],
            token=token,
            presenter_emails=b["presenter_emails"] or None,
            resource_id=None,
            schedule_headers=schedule_headers,
        )
        steps.append({"step": "push_agenda", "ok": bool(agenda_result.get("success")), "detail": agenda_result})

    entry["pushed"] = True
    failed = [s["step"] for s in steps if not s["ok"]]
    return {
        "success": not failed,
        "meeting_id": meeting_id,
        "steps": steps,
        "failed_steps": failed,
    }
