"""
Briefing builder — the write half of the agentic briefing flow.

In this tenant a briefing IS an event (category "Customer Briefing Request",
CBR-* numbers) created through the forms engine — not a "meeting" (that
subsystem belongs to the tradeshow module). See docs/BRIEFINGIQ_API_GUIDE.md.

Flow (strictly ordered):
  1. The agent interviews the user and gathers data (catalog / OpenSearch tools).
  2. draft_briefing(...)  → validates + assembles a complete draft, returns a
     draft_id and a human-readable summary. NO writes happen here.
  3. The agent shows the summary; the user must explicitly confirm.
  4. push_briefing(draft_id, ...) → executes the verified write chain:
        a. POST /forms/{requestFormId}/data       → creates the CBR event (requestId)
        b. PUT  .../data/{requestId}/actions/SUBMIT?sendNotification=false
        c. push_agenda_to_app(...)                → agenda sessions (optional)
     Partial failures are reported per step; completed steps are never rolled back.

The moduleId/journeyId/pageId/formId are discovered at runtime (they differ per
tenant): category with identifier REQUEST_TYPE → module with moduleType
REQUEST_CREATION → its journey/page/form config. Verified live 2026-07-17
(create → CBR-20260724-108 → SUBMIT → CANCEL, all 200).

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

_REQUEST_CTX_CACHE: Dict[str, Dict[str, Any]] = {}
_REQUEST_CTX_TTL = 3600


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


def _embedded_items(payload: Dict) -> List[Dict]:
    for value in (payload.get("_embedded") or {}).values():
        if isinstance(value, list):
            return value
    return []


def _fetch_event_locations(headers: Dict[str, str], event_id: str) -> List[Dict]:
    """Rooms attached to an event — used by briefing_editor to resolve room names."""
    url = f"{BASE_URL}/events/{event_id}/locations"
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            logger.warning(f"event locations fetch failed: HTTP {resp.status_code}")
            return []
        data = resp.json()
        return _embedded_items(data) or (data if isinstance(data, list) else [])
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
        return None, names, "No room requested."
    want = room_name.lower().strip()
    for loc in locations:
        name = _location_name(loc).lower()
        if want == name or want in name or name in want:
            return loc, names, None
    return None, names, f"Room '{room_name}' not found on this event."


def _discover_request_context(headers: Dict[str, str]) -> Dict[str, Any]:
    """
    Resolve the tenant's request-creation wiring at runtime:
      category (identifier REQUEST_TYPE) → module (moduleType REQUEST_CREATION)
      → module config (journey/page/form). Cached per tenant for an hour.
    """
    cache_key = headers.get("x-cloud-customerid", "")
    cached = _REQUEST_CTX_CACHE.get(cache_key)
    if cached and _now() - cached["ts"] < _REQUEST_CTX_TTL:
        return cached["ctx"]

    category_type = headers.get("x-cloud-categorytypeid", "CATEGORY_TYPE_BRIEFINGS")
    resp = requests.get(
        f"{BASE_URL}/categorytypes/{category_type}/categories", headers=headers, timeout=30
    )
    resp.raise_for_status()
    request_category = next(
        (c for c in _embedded_items(resp.json()) if c.get("identifier") == "REQUEST_TYPE"),
        None,
    )
    if not request_category:
        raise RuntimeError("No REQUEST_TYPE category found for this tenant.")

    req_headers = {**headers, "x-cloud-categoryid": request_category["uniqueId"]}

    resp = requests.get(f"{BASE_URL}/admin/moduleaccess", headers=req_headers, timeout=30)
    resp.raise_for_status()
    module_id = None
    for item in _embedded_items(resp.json()):
        module = item.get("module") or {}
        module_type = module.get("moduleType")
        type_id = module_type.get("uniqueId") if isinstance(module_type, dict) else module_type
        if type_id == "REQUEST_CREATION":
            module_id = module.get("uniqueId")
            break
    if not module_id:
        raise RuntimeError("No REQUEST_CREATION module accessible for this user.")

    resp = requests.get(f"{BASE_URL}/modules/{module_id}/configs", headers=req_headers, timeout=30)
    resp.raise_for_status()
    configs = _embedded_items(resp.json())
    if not configs:
        raise RuntimeError("Request-creation module has no journey/page/form config.")
    config = configs[0]

    ctx = {
        "category_id": request_category["uniqueId"],
        "module_id": module_id,
        "journey_id": (config.get("journey") or {}).get("uniqueId"),
        "page_id": (config.get("page") or {}).get("uniqueId"),
        "form_id": (config.get("form") or {}).get("uniqueId"),
    }
    if not ctx["form_id"]:
        raise RuntimeError("Module config is missing the create-request form id.")
    _REQUEST_CTX_CACHE[cache_key] = {"ts": _now(), "ctx": ctx}
    logger.info(f"discovered request context: {ctx}")
    return ctx


def draft_briefing(
    token: str,
    customer_name: str,
    briefing_date: str,
    start_time: str,
    end_time: str,
    opportunity_id: str = "",
    objective: Optional[str] = None,
    duration_days: int = 1,
    room_name: Optional[str] = None,
    presenter_emails: Optional[List[str]] = None,
    internal_attendees: Optional[List[Dict]] = None,
    external_attendees: Optional[List[Dict]] = None,
    agenda_sessions: Optional[List[Dict]] = None,
    schedule_headers: Optional[Dict] = None,
    event_id: str = "",  # unused in create flow; kept for call compatibility
) -> Dict[str, Any]:
    """
    Validate and assemble a briefing draft. NO writes. Returns draft_id + summary
    for user review. The create-request form requires customer name, opportunity
    id, date, start/end time, and duration (1-5 days).
    """
    _prune_drafts()

    missing = []
    if not customer_name:
        missing.append("customer_name")
    if not opportunity_id:
        missing.append("opportunity_id")
    for field, value in (("briefing_date", briefing_date), ("start_time", start_time), ("end_time", end_time)):
        if not value:
            missing.append(field)
    if missing:
        return {"success": False, "error": f"Missing required fields: {missing}"}
    if not 1 <= int(duration_days) <= 5:
        return {"success": False, "error": "duration_days must be between 1 and 5."}

    tz = _tz_name(schedule_headers)
    try:
        start_ms = _to_ms(briefing_date, start_time, tz)
        end_ms = _to_ms(briefing_date, end_time, tz)
    except ValueError as exc:
        return {"success": False, "error": f"Bad date/time format ({exc}). Use YYYY-MM-DD and HH:MM (24h)."}
    if end_ms <= start_ms:
        return {"success": False, "error": "end_time must be after start_time."}

    assumptions = []
    if not objective:
        assumptions.append("No objective provided.")
    if room_name:
        assumptions.append(
            f"Room preference '{room_name}' noted — room booking is a separate step after creation."
        )
    if internal_attendees or external_attendees:
        assumptions.append(
            "Attendees recorded on the draft; automated attendee push is not yet enabled."
        )

    briefing = {
        "customer_name": customer_name,
        "opportunity_id": opportunity_id,
        "objective": objective or "",
        "briefing_date": briefing_date,
        "start_time": start_time,
        "end_time": end_time,
        "duration_days": int(duration_days),
        "timezone": tz,
        "room_name": room_name,
        "presenter_emails": presenter_emails or [],
        "internal_attendees": internal_attendees or [],
        "external_attendees": external_attendees or [],
        "agenda_sessions": agenda_sessions or [],
    }

    draft_id = uuid.uuid4().hex[:12]
    _DRAFTS[draft_id] = {"created": _now(), "briefing": briefing, "pushed": False}

    lines = [
        f"**Customer:** {customer_name}",
        f"**Opportunity:** {opportunity_id}",
        f"**Objective:** {objective or '—'}",
        f"**Date:** {briefing_date}  {start_time}–{end_time} ({tz}), {duration_days} day(s)",
        f"**Room preference:** {room_name or '—'}",
        f"**Presenters:** {', '.join(presenter_emails) if presenter_emails else '—'}",
        f"**Agenda sessions:** {len(agenda_sessions or [])}",
    ]

    return {
        "success": True,
        "draft_id": draft_id,
        "summary_markdown": "\n".join(lines),
        "briefing": briefing,
        "assumptions": assumptions,
        "next_step": (
            "Show this summary to the user. Only call push_briefing after they explicitly confirm."
        ),
    }


def push_briefing(
    draft_id: str,
    token: str,
    schedule_headers: Optional[Dict] = None,
    submit: bool = True,
) -> Dict[str, Any]:
    """
    Execute the writes for a confirmed draft. Ordered, partial-failure tolerant:
    create request (forms engine) → SUBMIT state action → agenda sessions.
    """
    _prune_drafts()
    entry = _DRAFTS.get(draft_id)
    if entry is None:
        return {"success": False, "error": f"Draft '{draft_id}' not found or expired. Re-run draft_briefing."}
    if entry["pushed"]:
        return {"success": False, "error": f"Draft '{draft_id}' was already pushed — refusing to push twice."}

    b = entry["briefing"]
    headers = _make_headers(token, None, schedule_headers)
    steps: List[Dict[str, Any]] = []

    # ── Step 0: discover the tenant's request-creation wiring ─────────────
    try:
        ctx = _discover_request_context(headers)
    except Exception as exc:
        return {"success": False, "steps": [{"step": "discover_context", "ok": False, "error": str(exc)}]}
    headers["x-cloud-categoryid"] = ctx["category_id"]

    # ── Step 1: create the briefing request via the forms engine ──────────
    form_id = ctx["form_id"]
    payload = {
        "moduleId": ctx["module_id"],
        "formId": form_id,
        "journeyId": ctx["journey_id"],
        "pageId": ctx["page_id"],
        "data": {
            "duration": b["duration_days"],
            "startDate": {"isoDate": b["briefing_date"]},
            "startTime": {"isoDate": f"{b['briefing_date']}T{b['start_time']}:00"},
            "endTime": {"isoDate": f"{b['briefing_date']}T{b['end_time']}:00"},
            "textField1": b["customer_name"],
            "textField2": b["opportunity_id"],
        },
    }
    if b["objective"]:
        payload["data"]["textField3"] = b["objective"]

    url = f"{BASE_URL}/forms/{form_id}/data"
    logger.info(f"push_briefing {draft_id}: POST {url}")
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
    except requests.RequestException as exc:
        return {"success": False, "steps": [{"step": "create_request", "ok": False, "error": str(exc)}]}

    body = {}
    if resp.status_code == 200 and resp.text.strip():
        try:
            body = resp.json()
        except ValueError:
            pass
    request_id = body.get("id")
    if not request_id:
        return {
            "success": False,
            "steps": [{
                "step": "create_request", "ok": False,
                "error": f"HTTP {resp.status_code}, no request id returned — briefing NOT created.",
                "body": resp.text[:500],
            }],
        }
    steps.append({"step": "create_request", "ok": True, "request_id": request_id})

    # Fetch the created event for its CBR number (nice for the user-facing summary).
    event_number = None
    try:
        ev = requests.get(f"{BASE_URL}/events/{request_id}", headers=headers, timeout=30)
        if ev.status_code == 200:
            event_number = ev.json().get("eventNumber")
    except requests.RequestException:
        pass

    request_headers = {**headers, "x-cloud-eventid": request_id}

    # ── Step 2: SUBMIT state action (no notifications) ────────────────────
    if submit:
        action_url = f"{BASE_URL}/forms/{form_id}/data/{request_id}/actions/SUBMIT"
        try:
            a_resp = requests.put(
                action_url, headers=request_headers,
                params={"sendNotification": "false"}, json={}, timeout=30,
            )
            ok = a_resp.status_code in (200, 204)
            step: Dict[str, Any] = {"step": "submit", "ok": ok}
            if not ok:
                step["error"] = f"HTTP {a_resp.status_code}"
                step["body"] = a_resp.text[:300]
            steps.append(step)
        except requests.RequestException as exc:
            steps.append({"step": "submit", "ok": False, "error": str(exc)})

    # ── Step 3: agenda sessions (optional, reuses the proven agenda push) ─
    if b["agenda_sessions"]:
        agenda_result = push_agenda_to_app(
            event_id=request_id,
            event_date=b["briefing_date"],
            sessions=b["agenda_sessions"],
            token=token,
            presenter_emails=b["presenter_emails"] or None,
            resource_id=None,
            schedule_headers=schedule_headers,
        )
        steps.append({"step": "push_agenda", "ok": bool(agenda_result.get("success")), "detail": agenda_result})

    if b["internal_attendees"] or b["external_attendees"]:
        steps.append({
            "step": "attendees", "ok": True, "skipped": True,
            "note": "Attendee push not yet automated — add them in the app.",
        })

    entry["pushed"] = True
    failed = [s["step"] for s in steps if not s["ok"]]
    return {
        "success": not failed,
        "request_id": request_id,
        "event_number": event_number,
        "steps": steps,
        "failed_steps": failed,
    }
