"""
Briefing editor — surgical, confirmation-gated edits to EXISTING briefings
(meetings), whether they were created via push_briefing or manually in the app.

Every function here follows the same miniature confirm pattern as the builder:
the agent must first show the user the exact change (find the meeting via the
read tools, present current → proposed), and only call these after an explicit
"yes". Each call performs one focused write against the caller's own session,
so server-side RBAC applies.

Write surface:
  - reschedule_briefing        PUT  /meetings/{mid}/actions/RESCHEDULE
  - manage_briefing_attendees  POST/PUT/DELETE /events/{eid}/meetings/{mid}/{attendeetype}[/{attendeeid}]
  - manage_briefing_presenters POST/DELETE/PATCH /events/{eid}/meetings/{mid}/presenters[...]
  - update_briefing_details    GET + PUT /events/{eid}/meetings/{mid}  (read-modify-write of the data map)
"""
from typing import Any, Dict, List, Optional

import requests

from logging_config import get_logger
from tools.briefing_builder import _resolve_room, _to_ms, _tz_name
from tools.briefingiq_writer import BASE_URL, _make_headers

logger = get_logger(__name__)


def _err(step: str, resp: Optional[requests.Response] = None, exc: Optional[Exception] = None) -> Dict:
    if exc is not None:
        return {"success": False, "step": step, "error": str(exc)}
    return {
        "success": False,
        "step": step,
        "error": f"HTTP {resp.status_code}",
        "body": resp.text[:500],
    }


def _get_meeting(headers: Dict, event_id: str, meeting_id: str) -> Optional[Dict]:
    url = f"{BASE_URL}/events/{event_id}/meetings/{meeting_id}"
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        return resp.json() if resp.status_code == 200 else None
    except requests.RequestException:
        return None


def reschedule_briefing(
    event_id: str,
    meeting_id: str,
    token: str,
    new_date: str,
    start_time: str,
    end_time: str,
    room_name: Optional[str] = None,
    schedule_headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Move an existing briefing to a new date/time (and optionally a new room)."""
    headers = _make_headers(token, event_id, schedule_headers)
    tz = _tz_name(schedule_headers)
    try:
        day_ms = _to_ms(new_date, "00:00", tz)
        start_ms = _to_ms(new_date, start_time, tz)
        end_ms = _to_ms(new_date, end_time, tz)
    except ValueError as exc:
        return {"success": False, "error": f"Bad date/time ({exc}). Use YYYY-MM-DD and HH:MM."}
    if end_ms <= start_ms:
        return {"success": False, "error": "end_time must be after start_time."}

    request_date: Dict[str, Any] = {
        "requestDate": day_ms,
        "requestedStartTime": start_ms,
        "requestedEndTime": end_ms,
    }
    if room_name:
        location, options, note = _resolve_room(headers, event_id, room_name)
        if not location:
            return {"success": False, "error": note, "room_options": options}
        request_date["location"] = {"uniqueId": location["uniqueId"]}

    payload: Dict[str, Any] = {"requestDates": [request_date]}

    # The reschedule action wants the current bookingId when one exists.
    meeting = _get_meeting(headers, event_id, meeting_id)
    booking_id = (meeting or {}).get("bookingId")
    if booking_id:
        payload["bookingId"] = booking_id

    url = f"{BASE_URL}/meetings/{meeting_id}/actions/RESCHEDULE"
    logger.info(f"reschedule_briefing: PUT {url}")
    try:
        resp = requests.put(url, headers=headers, json=payload, timeout=30)
    except requests.RequestException as exc:
        return _err("reschedule", exc=exc)
    if resp.status_code not in (200, 201):
        return _err("reschedule", resp)
    return {"success": True, "meeting_id": meeting_id, "rescheduled_to": f"{new_date} {start_time}–{end_time} ({tz})", "response": resp.json() if resp.text else {}}


def manage_briefing_attendees(
    event_id: str,
    meeting_id: str,
    token: str,
    action: str,
    attendee_type: str,
    attendee: Optional[Dict] = None,
    attendee_id: Optional[str] = None,
    schedule_headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    add    → POST   .../{attendeetype}            (attendee body required)
    update → PUT    .../{attendeetype}/{id}       (attendee body + attendee_id)
    remove → DELETE .../{attendeetype}/{id}       (attendee_id required)
    attendee_type: 'internalattendees' | 'externalattendees'
    """
    headers = _make_headers(token, event_id, schedule_headers)
    base = f"{BASE_URL}/events/{event_id}/meetings/{meeting_id}/{attendee_type}"

    try:
        if action == "add":
            if not attendee:
                return {"success": False, "error": "attendee body required for add."}
            resp = requests.post(base, headers=headers, json=attendee, timeout=30)
        elif action == "update":
            if not (attendee and attendee_id):
                return {"success": False, "error": "attendee body and attendee_id required for update."}
            resp = requests.put(f"{base}/{attendee_id}", headers=headers, json=attendee, timeout=30)
        elif action == "remove":
            if not attendee_id:
                return {"success": False, "error": "attendee_id required for remove."}
            resp = requests.delete(f"{base}/{attendee_id}", headers=headers, timeout=30)
        else:
            return {"success": False, "error": f"Unknown action '{action}' — use add | update | remove."}
    except requests.RequestException as exc:
        return _err(f"attendee_{action}", exc=exc)

    if resp.status_code not in (200, 201, 204):
        return _err(f"attendee_{action}", resp)
    return {"success": True, "action": action, "attendee_type": attendee_type, "response": resp.json() if resp.text else {}}


def manage_briefing_presenters(
    event_id: str,
    meeting_id: str,
    token: str,
    action: str,
    email: Optional[str] = None,
    presenter_id: Optional[str] = None,
    status: Optional[str] = None,
    schedule_headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    add        → POST   .../presenters   ({primaryEmail: [email], isNewPresenter: false})
    remove     → DELETE .../presenters/{presenter_id}
    set_status → PATCH  .../presenters/{presenter_id}/{status}
    """
    headers = _make_headers(token, event_id, schedule_headers)
    base = f"{BASE_URL}/events/{event_id}/meetings/{meeting_id}/presenters"

    try:
        if action == "add":
            if not email:
                return {"success": False, "error": "email required for add."}
            body = {"primaryEmail": [email], "isNewPresenter": False}
            resp = requests.post(base, headers=headers, json=body, timeout=30)
        elif action == "remove":
            if not presenter_id:
                return {"success": False, "error": "presenter_id required for remove."}
            resp = requests.delete(f"{base}/{presenter_id}", headers=headers, timeout=30)
        elif action == "set_status":
            if not (presenter_id and status):
                return {"success": False, "error": "presenter_id and status required for set_status."}
            resp = requests.patch(f"{base}/{presenter_id}/{status}", headers=headers, timeout=30)
        else:
            return {"success": False, "error": f"Unknown action '{action}' — use add | remove | set_status."}
    except requests.RequestException as exc:
        return _err(f"presenter_{action}", exc=exc)

    if resp.status_code not in (200, 201, 204):
        return _err(f"presenter_{action}", resp)
    return {"success": True, "action": action, "response": resp.json() if resp.text else {}}


def update_briefing_details(
    event_id: str,
    meeting_id: str,
    token: str,
    changes: Dict[str, Any],
    schedule_headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Read-modify-write of the meeting's data map (accountName, meetingDetails,
    meetingFocus, industry, numberOfAttendees, opportunity, host fields, ...).
    Only the keys in `changes` are altered; everything else is preserved.
    """
    if not changes:
        return {"success": False, "error": "No changes given."}

    headers = _make_headers(token, event_id, schedule_headers)
    meeting = _get_meeting(headers, event_id, meeting_id)
    if meeting is None:
        return {"success": False, "error": f"Could not fetch meeting {meeting_id} to apply changes."}

    data = dict(meeting.get("data") or {})
    before = {k: data.get(k) for k in changes}
    data.update(changes)

    payload: Dict[str, Any] = {"data": data}
    # Preserve presenters if the GET returned them — the PUT example includes them.
    if meeting.get("presenters"):
        payload["presenters"] = meeting["presenters"]

    url = f"{BASE_URL}/events/{event_id}/meetings/{meeting_id}"
    logger.info(f"update_briefing_details: PUT {url} keys={list(changes)}")
    try:
        resp = requests.put(url, headers=headers, json=payload, timeout=30)
    except requests.RequestException as exc:
        return _err("update_details", exc=exc)
    if resp.status_code not in (200, 201):
        return _err("update_details", resp)
    return {"success": True, "changed": {k: {"from": before[k], "to": changes[k]} for k in changes}}
