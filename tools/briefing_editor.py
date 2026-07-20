"""
Briefing editor — surgical, confirmation-gated edits to EXISTING briefings,
whether created by the agent (push_briefing) or by hand in the app.

A briefing is a CBR event backed by a request form, so every edit is a
read-modify-write of that form's data map, or a state action. See
docs/BRIEFINGIQ_API_GUIDE.md.

  update_briefing_details  PUT /forms/{formId}/data/{requestId}
  reschedule_briefing      same PUT, changing startDate/startTime/endTime
  change_briefing_state    PUT /forms/{formId}/data/{requestId}/actions/{ACTION}
  get_briefing             GET, for showing the user current values first

Field mirroring (the non-obvious part): the data map carries every field twice —
a semantic alias and the raw column attribute (customerName ↔ textField1,
primaryOpportunity ↔ textField2, …). A write only sticks if BOTH are set, so
`_apply_updates` mirrors each change using the form's own fieldmappings.
Multi-value fields (opportunity, secondaryOpportunity) must be lists.

Every function follows the confirm pattern: the agent shows current → proposed
and only calls these after an explicit user "yes". Writes use the caller's own
session, so server-side RBAC applies.
"""
from typing import Any, Dict, List, Optional, Tuple

import requests

from logging_config import get_logger
from tools.briefing_builder import (
    _discover_request_context,
    _embedded_items,
    _now,
    _to_ms,
    _tz_name,
)
from tools.briefingiq_writer import BASE_URL, _make_headers

logger = get_logger(__name__)

_ALIAS_CACHE: Dict[str, Dict[str, Any]] = {}
_ALIAS_TTL = 3600

# Actions that end/park a briefing — surfaced in the result so the agent can
# warn the user before firing one.
TERMINAL_ACTIONS = {"CANCEL", "DECLINE", "DELETE"}


def _err(step: str, resp: Optional[requests.Response] = None, exc: Optional[Exception] = None) -> Dict:
    if exc is not None:
        return {"success": False, "step": step, "error": str(exc)}
    return {"success": False, "step": step, "error": f"HTTP {resp.status_code}", "body": resp.text[:400]}


def _fetch_field_aliases(headers: Dict[str, str], form_id: str) -> Dict[str, Any]:
    """
    Build the alias↔raw-attribute map for a form from its fieldmappings.

    Returns {"pairs": {name: (alias, attr)}, "multi": {names...}} where every
    alias and attribute name keys into the same (alias, attr) tuple.
    """
    cached = _ALIAS_CACHE.get(form_id)
    if cached and _now() - cached["ts"] < _ALIAS_TTL:
        return cached["map"]

    # Must be fetched WITHOUT x-cloud-eventid: with it, the server scopes the
    # lookup to the event and returns an empty page.
    lookup_headers = {k: v for k, v in headers.items() if k.lower() != "x-cloud-eventid"}
    resp = requests.get(f"{BASE_URL}/forms/{form_id}/fieldmappings", headers=lookup_headers, timeout=30)
    resp.raise_for_status()

    pairs: Dict[str, Tuple[str, str]] = {}
    multi: set = set()
    for mapping in _embedded_items(resp.json()):
        column = mapping.get("columnAttribute") or {}
        attr = column.get("attributeName")
        alias = mapping.get("aliasName") or attr
        if not attr:
            continue
        pairs[alias] = (alias, attr)
        pairs[attr] = (alias, attr)
        if mapping.get("multivalueField"):
            multi.update({alias, attr})

    alias_map = {"pairs": pairs, "multi": multi}
    _ALIAS_CACHE[form_id] = {"ts": _now(), "map": alias_map}
    return alias_map


def _apply_updates(data: Dict[str, Any], changes: Dict[str, Any], alias_map: Dict[str, Any]) -> Tuple[Dict, List[str]]:
    """Write each change to both its alias and raw attribute. Returns (data, unknown_fields)."""
    pairs, multi = alias_map["pairs"], alias_map["multi"]
    unknown = []
    for field, value in changes.items():
        pair = pairs.get(field)
        if pair is None:
            unknown.append(field)
            continue
        for name in pair:
            data[name] = ([value] if not isinstance(value, list) else value) if name in multi else value
    return data, unknown


def _load_request(headers: Dict[str, str], form_id: str, request_id: str) -> Optional[Dict]:
    resp = requests.get(f"{BASE_URL}/forms/{form_id}/data/{request_id}", headers=headers, timeout=30)
    return resp.json() if resp.status_code == 200 else None


def _context_for(token: str, request_id: str, schedule_headers: Optional[Dict]) -> Tuple[Dict, Dict]:
    """Returns (request-scoped headers, discovered tenant context)."""
    headers = _make_headers(token, None, schedule_headers)
    ctx = _discover_request_context(headers)
    headers["x-cloud-categoryid"] = ctx["category_id"]
    headers["x-cloud-eventid"] = request_id
    return headers, ctx


def _put_form_data(headers: Dict, ctx: Dict, request_id: str, data: Dict) -> requests.Response:
    body = {
        "moduleId": ctx["module_id"],
        "formId": ctx["form_id"],
        "journeyId": ctx["journey_id"],
        "pageId": ctx["page_id"],
        "data": data,
    }
    return requests.put(
        f"{BASE_URL}/forms/{ctx['form_id']}/data/{request_id}", headers=headers, json=body, timeout=30
    )


def _summarize(data: Dict) -> Dict[str, Any]:
    def cloud(value, key):
        return value.get(key) if isinstance(value, dict) else value

    start_date = data.get("startDate")
    return {
        "customer_name": data.get("customerName"),
        "primary_opportunity": data.get("primaryOpportunity"),
        "date": (cloud(start_date, "zoneDate") or "")[:10] if isinstance(start_date, dict) else start_date,
        "start_time": cloud(data.get("startTime"), "zoneTime"),
        "end_time": cloud(data.get("endTime"), "zoneTime"),
        "duration_days": data.get("duration"),
        "region": data.get("region"),
        "tier": data.get("tier"),
        "briefing_manager": data.get("briefingManager"),
    }


def get_briefing(request_id: str, token: str, schedule_headers: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Read a briefing's current field values, status, and the state actions
    available from that status. Use this to show the user what will change.
    """
    try:
        headers, ctx = _context_for(token, request_id, schedule_headers)
    except Exception as exc:
        return {"success": False, "error": f"Could not resolve tenant context: {exc}"}

    request = _load_request(headers, ctx["form_id"], request_id)
    if request is None:
        return {"success": False, "error": f"Briefing '{request_id}' not found."}

    event, actions = {}, []
    try:
        ev_resp = requests.get(f"{BASE_URL}/events/{request_id}", headers=headers, timeout=30)
        if ev_resp.status_code == 200:
            event = ev_resp.json()
            actions = [
                name for name, link in (event.get("_links") or {}).items()
                if isinstance(link, dict) and link.get("type") == "STATE_ACTION"
            ]
    except requests.RequestException:
        pass

    alias_map = _fetch_field_aliases(headers, ctx["form_id"])
    editable = sorted({alias for alias, _ in alias_map["pairs"].values()})

    return {
        "success": True,
        "request_id": request_id,
        "event_number": event.get("eventNumber"),
        "status": (event.get("status") or {}).get("stateCode"),
        "fields": _summarize(request.get("data") or {}),
        "available_actions": actions,
        "editable_fields": editable,
    }


def update_briefing_details(
    request_id: str,
    token: str,
    changes: Dict[str, Any],
    schedule_headers: Optional[Dict] = None,
    event_id: str = "",  # accepted for call-compatibility; request_id is authoritative
) -> Dict[str, Any]:
    """
    Read-modify-write of the briefing's form fields. Only the keys in `changes`
    are altered (each mirrored to its raw attribute); everything else is
    preserved. Accepts semantic names: customerName, primaryOpportunity,
    secondaryOpportunity, region, tier, briefingManager, accountId, duration.
    """
    if not changes:
        return {"success": False, "error": "No changes given."}

    try:
        headers, ctx = _context_for(token, request_id, schedule_headers)
    except Exception as exc:
        return {"success": False, "error": f"Could not resolve tenant context: {exc}"}

    request = _load_request(headers, ctx["form_id"], request_id)
    if request is None:
        return {"success": False, "error": f"Briefing '{request_id}' not found."}

    data = dict(request.get("data") or {})
    before = _summarize(data)
    alias_map = _fetch_field_aliases(headers, ctx["form_id"])
    data, unknown = _apply_updates(data, changes, alias_map)
    if unknown:
        return {
            "success": False,
            "error": f"Unknown field(s): {unknown}",
            "editable_fields": sorted({a for a, _ in alias_map["pairs"].values()}),
        }

    logger.info(f"update_briefing_details {request_id}: {list(changes)}")
    try:
        resp = _put_form_data(headers, ctx, request_id, data)
    except requests.RequestException as exc:
        return _err("update_details", exc=exc)
    if resp.status_code not in (200, 201):
        return _err("update_details", resp)

    after = _summarize((_load_request(headers, ctx["form_id"], request_id) or {}).get("data") or {})
    applied = {k: v for k, v in after.items() if before.get(k) != v}
    return {
        "success": True,
        "request_id": request_id,
        "changed": applied or None,
        "before": {k: before[k] for k in applied} if applied else None,
        "note": None if applied else "Server accepted the update but no summary field changed.",
    }


def reschedule_briefing(
    request_id: str,
    token: str,
    new_date: str,
    start_time: str,
    end_time: str,
    duration_days: Optional[int] = None,
    schedule_headers: Optional[Dict] = None,
    event_id: str = "",
    room_name: Optional[str] = None,  # accepted but not applied; see note below
) -> Dict[str, Any]:
    """
    Move a briefing to a new date/time by updating its form dates. (The
    RESCHEDULE state action exists but rejected every payload shape tried
    against it; the form-data write is the verified path.)
    """
    tz = _tz_name(schedule_headers)
    try:
        start_ms = _to_ms(new_date, start_time, tz)
        end_ms = _to_ms(new_date, end_time, tz)
    except ValueError as exc:
        return {"success": False, "error": f"Bad date/time ({exc}). Use YYYY-MM-DD and HH:MM."}
    if end_ms <= start_ms:
        return {"success": False, "error": "end_time must be after start_time."}
    if duration_days is not None and not 1 <= int(duration_days) <= 5:
        return {"success": False, "error": "duration_days must be between 1 and 5."}

    try:
        headers, ctx = _context_for(token, request_id, schedule_headers)
    except Exception as exc:
        return {"success": False, "error": f"Could not resolve tenant context: {exc}"}

    request = _load_request(headers, ctx["form_id"], request_id)
    if request is None:
        return {"success": False, "error": f"Briefing '{request_id}' not found."}

    data = dict(request.get("data") or {})
    before = _summarize(data)
    data["startDate"] = {"isoDate": new_date}
    if "eventDate" in data:
        data["eventDate"] = {"isoDate": new_date}
    data["startTime"] = {"isoDate": f"{new_date}T{start_time}:00"}
    data["endTime"] = {"isoDate": f"{new_date}T{end_time}:00"}
    if duration_days is not None:
        data["duration"] = int(duration_days)

    logger.info(f"reschedule_briefing {request_id} → {new_date} {start_time}-{end_time}")
    try:
        resp = _put_form_data(headers, ctx, request_id, data)
    except requests.RequestException as exc:
        return _err("reschedule", exc=exc)
    if resp.status_code not in (200, 201):
        return _err("reschedule", resp)

    after = _summarize((_load_request(headers, ctx["form_id"], request_id) or {}).get("data") or {})
    keys = ("date", "start_time", "end_time")
    result = {
        "success": True,
        "request_id": request_id,
        "before": {k: before[k] for k in keys},
        "after": {k: after[k] for k in keys},
    }
    if room_name:
        result["note"] = (
            f"Room '{room_name}' was NOT changed — room assignment is a separate "
            "step and is not automated yet."
        )
    return result


def change_briefing_state(
    request_id: str,
    token: str,
    action: str,
    send_notification: bool = False,
    schedule_headers: Optional[Dict] = None,
    event_id: str = "",
) -> Dict[str, Any]:
    """
    Fire a state action on a briefing (SUBMIT, CONFIRM, HOLD, WAITLIST, CANCEL,
    DECLINE, …). Valid actions depend on the current status — get_briefing lists
    them. Notifications are OFF by default; the agent must ask the user before
    enabling them, since they email real customers.
    """
    action = (action or "").strip().upper()
    if not action:
        return {"success": False, "error": "No action given."}

    try:
        headers, ctx = _context_for(token, request_id, schedule_headers)
    except Exception as exc:
        return {"success": False, "error": f"Could not resolve tenant context: {exc}"}

    current = get_briefing(request_id, token, schedule_headers)
    if not current.get("success"):
        return current
    available = current.get("available_actions") or []
    if available and action not in available:
        return {
            "success": False,
            "error": f"'{action}' is not available from status '{current.get('status')}'.",
            "available_actions": available,
        }

    url = f"{BASE_URL}/forms/{ctx['form_id']}/data/{request_id}/actions/{action}"
    logger.info(f"change_briefing_state {request_id}: {action} (notify={send_notification})")
    try:
        resp = requests.put(
            url, headers=headers,
            params={"sendNotification": "true" if send_notification else "false"},
            json={}, timeout=30,
        )
    except requests.RequestException as exc:
        return _err(f"action_{action}", exc=exc)
    if resp.status_code not in (200, 204):
        return _err(f"action_{action}", resp)

    after = get_briefing(request_id, token, schedule_headers)
    return {
        "success": True,
        "request_id": request_id,
        "action": action,
        "status_before": current.get("status"),
        "status_after": after.get("status"),
        "notifications_sent": send_notification,
        "terminal": action in TERMINAL_ACTIONS,
    }
