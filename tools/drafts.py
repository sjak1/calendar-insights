"""
Draft generation tools — confirmation emails and catering/setup sheets.

The confirmation email tool fetches event data, then delegates writing the email
body to a fast sub-LLM call (Haiku) with a focused prompt. This gives polished,
adaptive output without paying the cost of the main agent rendering the body in
its primary context.

The catering sheet still uses Python templating + keyword inference for setup
needs — deterministic ops output is more important than prose flexibility there.
"""

import json as _json
import os
import time
from datetime import datetime, timezone as _timezone
from typing import Any, Dict, List, Optional

from logging_config import get_logger

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────
# Sub-LLM prompt — Haiku composes the email from structured event data
# ─────────────────────────────────────────────────────────────

EMAIL_COMPOSER_SYSTEM = (
    "You are a senior Executive Briefing Center (EBC) manager at a large enterprise "
    "tech company, writing customer-facing confirmation emails. Tone: warm, "
    "professional, concise. Use clean plain-text formatting (no markdown tables). "
    "Sections: greeting → confirmation paragraph → Event Details block → Agenda "
    "Overview block → close → signature. End the email with the host's name + "
    "email. Output ONLY the email — start with 'Subject:' on the first line, "
    "blank line, then body. No preamble, no commentary."
)

# Default sub-LLM model. Haiku 4.5 is ~2x faster than Sonnet for this kind of
# small structured-input → short-form-text task and the quality is plenty good.
EMAIL_COMPOSER_MODEL_ID = (
    os.getenv("EMAIL_COMPOSER_MODEL_ID")
    or "us.anthropic.claude-haiku-4-5-20251001-v1:0"
)


# ─────────────────────────────────────────────────────────────
# Activity type → setup/catering inference rules
# Checked in order; first match wins. Prefer matching against
# activity_type (structured) before falling back to title keywords.
# ─────────────────────────────────────────────────────────────

CATERING_RULES = [
    (("lunch", "dinner", "breakfast", "meal", "reception", "banquet", "catering", "food"),
     "Full catering required"),
    (("coffee", "tea", "break", "refreshment", "snack"),
     "Refreshments / coffee service"),
]
CATERING_DEFAULT = "Water / beverages"

SETUP_RULES = [
    (("demo", "lab", "technical", "product", "hands-on", "workshop"),
     ["Demo stations / lab setup", "AV: projector + display screens"]),
    (("executive", "boardroom", "strategy", "keynote", "leadership"),
     ["Executive seating arrangement", "AV: large display + video conf"]),
    (("panel", "discussion", "roundtable"),
     ["Roundtable seating", "AV: mics + display"]),
]
SETUP_DEFAULT = ["AV: projector + screen"]


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _epoch_ms_to_readable(ms: Any, fmt: str = "%B %d, %Y at %I:%M %p") -> str:
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=_timezone.utc).strftime(fmt)
    except Exception:
        return str(ms)


def _epoch_ms_to_date(ms: Any) -> str:
    return _epoch_ms_to_readable(ms, "%B %d, %Y")


def _epoch_ms_to_time(ms: Any) -> str:
    return _epoch_ms_to_readable(ms, "%I:%M %p")


def _fmt_iso_time(iso: str) -> str:
    """Convert ISO datetime to 'I:MM AM' format, falling back to the raw value."""
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%I:%M %p")
    except Exception:
        return iso


def _deep_get(d: Any, path: str, default=None) -> Any:
    for key in path.split("."):
        if isinstance(d, dict):
            d = d.get(key)
        else:
            return default
    return d if d is not None else default


def _stringify_address(addr: Any) -> str:
    """Address might be a string or a dict of {street, city, state, zip}. Render safely."""
    if not addr:
        return ""
    if isinstance(addr, str):
        return addr
    if isinstance(addr, dict):
        parts = [
            addr.get("street") or addr.get("addressLine1") or "",
            addr.get("city", ""),
            addr.get("state", ""),
            addr.get("zip") or addr.get("postalCode") or "",
        ]
        return ", ".join(p for p in parts if p)
    return str(addr)


def _categorize(text: str, rules: List, default):
    """Return the first matching rule value for the given text (lowercased), else default."""
    t = text.lower()
    for keywords, value in rules:
        if any(k in t for k in keywords):
            return value
    return default


def _fetch_event(event_id: str) -> Dict[str, Any]:
    """Pull core event fields via the shared event_resolver (UUID→numeric, correct paths)."""
    try:
        from tools.event_resolver import fetch_event_data
        return fetch_event_data(event_id)
    except Exception as e:
        logger.warning(f"Event fetch failed: {e}")
        return {}


def _fetch_activities(event_id: str, token: str, schedule_headers: Dict) -> List[Dict]:
    """Pull activities list from BriefingIQ API."""
    try:
        from tools import list_event_activities
        return list_event_activities(token, schedule_headers, event_id=event_id)
    except Exception as e:
        logger.warning(f"Activities fetch failed: {e}")
        return []


def _extract_customer_emails(evt: Dict) -> List[str]:
    """Pull customer/attendee emails from a fetch_event_data() result."""
    emails = set()
    for attendee in evt.get("external_attendees", []):
        if isinstance(attendee, dict):
            email = attendee.get("email") or attendee.get("primaryEmail")
            if email:
                emails.add(email)
    # requesterEmail / customerEmail sometimes live on the visit info — peek into raw if needed
    raw_visit = _deep_get(evt.get("_raw") or {}, "eventFormData.VISIT_INFO") or {}
    if isinstance(raw_visit, list):
        raw_visit = raw_visit[0] if raw_visit else {}
    for field in ("customerEmail", "requesterEmail", "primaryEmail"):
        v = raw_visit.get(field) if isinstance(raw_visit, dict) else None
        if v:
            emails.add(v)
    return sorted(emails)


# ─────────────────────────────────────────────────────────────
# 6.2  Draft confirmation email
# ─────────────────────────────────────────────────────────────

def _compose_email_with_llm(payload: Dict[str, Any]) -> Dict[str, str]:
    """
    Send the structured event payload to a fast sub-LLM (Haiku) and return
    {'subject': ..., 'body': ...}. Falls back to a minimal templated draft
    if the call fails — caller always gets *something* usable.
    """
    user_prompt = (
        "Compose a confirmation email for the customer from this event data. "
        "Use only fields that are present; skip anything that is null/empty. "
        "Be concise — 200-350 words.\n\n"
        f"{_json.dumps(payload, indent=2, default=str)}"
    )

    try:
        from bedrock_llm import converse as bedrock_converse
        t0 = time.time()
        resp = bedrock_converse(
            messages=[{"role": "user", "content": [{"text": user_prompt}]}],
            system=[{"text": EMAIL_COMPOSER_SYSTEM}],
            tool_config={
                "tools": [{
                    "toolSpec": {
                        "name": "_noop",
                        "description": "unused",
                        "inputSchema": {"json": {"type": "object", "properties": {}}},
                    }
                }],
                "toolChoice": {"auto": {}},
            },
            model_id=EMAIL_COMPOSER_MODEL_ID,
        )
        elapsed = time.time() - t0
        usage = resp.get("usage", {})
        out_msg = resp.get("output", {}).get("message", {})
        text = "".join(b.get("text", "") for b in out_msg.get("content", []) if "text" in b).strip()

        # Split "Subject: ..." line from body
        subject = ""
        body = text
        for sep in ("\n\n", "\n"):
            if text.lower().startswith("subject:"):
                first, _, rest = text.partition(sep)
                if first.lower().startswith("subject:"):
                    subject = first.split(":", 1)[1].strip()
                    body = rest.lstrip()
                    break

        logger.info(
            f"Composed email via {EMAIL_COMPOSER_MODEL_ID.split('.')[-1]} in {elapsed:.2f}s "
            f"(in={usage.get('inputTokens')}, out={usage.get('outputTokens')})"
        )
        return {"subject": subject, "body": body}
    except Exception as e:
        logger.warning(f"Sub-LLM email composition failed: {e} — falling back to minimal draft")
        cust = payload.get("customer_name") or "Valued Customer"
        date = payload.get("event_date") or "TBD"
        host = payload.get("host_name") or "Your EBC Host"
        return {
            "subject": f"Confirmed: {payload.get('event_name', 'Executive Briefing')} — {date}",
            "body": f"Dear {cust} Team,\n\nWe are pleased to confirm your upcoming Executive Briefing.\n\nWarm regards,\n{host}\nEBC Team",
        }


def draft_confirmation_email(
    event_id: str,
    schedule_headers: Optional[Dict] = None,
    additional_notes: Optional[str] = None,
    host_name: Optional[str] = None,
    host_email: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Draft a professional confirmation email by combining live event data with
    a focused sub-LLM (Haiku) writing the actual prose. Returns subject + body.
    """
    headers = schedule_headers or {}
    token = headers.get("Authorization", "")

    evt = _fetch_event(event_id)
    activities = _fetch_activities(event_id, token, headers)

    if not evt and not activities:
        return {
            "success": False,
            "error": f"No event or activities found for event_id={event_id}",
            "event_id": event_id,
        }

    start_ms = evt.get("start_time_ms")
    end_ms   = evt.get("end_time_ms")
    event_date = _epoch_ms_to_date(start_ms) if start_ms else None
    time_range = None
    if start_ms and end_ms:
        time_range = f"{_epoch_ms_to_time(start_ms)} – {_epoch_ms_to_time(end_ms)}"
    elif start_ms:
        time_range = _epoch_ms_to_time(start_ms)

    # Sessions: keep up to 8 to give the LLM enough agenda detail without bloating context
    sessions = []
    for act in activities[:8]:
        sessions.append({
            "title": act.get("title") or act.get("activity_type"),
            "time":  _fmt_iso_time(act.get("start_iso", "")) or None,
            "room":  act.get("room_name"),
        })

    # Structured payload — only non-empty fields make it through
    payload = {k: v for k, v in {
        "customer_name":     evt.get("customer_name"),
        "event_name":        evt.get("event_name"),
        "event_date":        event_date,
        "time_range":        time_range,
        "location_name":     evt.get("location_name"),
        "location_address":  _stringify_address(evt.get("location_address") or ""),
        "visit_focus":       evt.get("visit_focus"),
        "customer_industry": evt.get("customer_industry"),
        "num_attendees":     evt.get("num_attendees"),
        "host_name":         host_name or evt.get("host_name"),
        "host_email":        host_email or evt.get("host_email"),
        "host_title":        evt.get("host_business_title"),
        "sessions":          sessions if sessions else None,
        "additional_notes":  additional_notes,
    }.items() if v}

    composed = _compose_email_with_llm(payload)

    to_emails = _extract_customer_emails(evt)
    customer_name = evt.get("customer_name") or "Valued Customer"
    final_date = event_date or "TBD"
    _host_email = host_email or evt.get("host_email") or ""

    logger.info(
        f"Drafted confirmation email for event {event_id} — {customer_name}, {final_date}, "
        f"{len(to_emails)} recipient(s)"
    )
    return {
        "success": True,
        "type": "confirmation_email",
        "subject": composed.get("subject") or f"Confirmed: {evt.get('event_name', 'Executive Briefing')} — {final_date}",
        "body": (composed.get("body") or "").strip(),
        "to": to_emails,
        "from_email": _host_email,
        "event_id": event_id,
        "customer_name": customer_name,
        "event_date": final_date,
    }


# ─────────────────────────────────────────────────────────────
# 6.3  Draft catering / setup sheet
# ─────────────────────────────────────────────────────────────

def draft_catering_sheet(
    event_id: str,
    schedule_headers: Optional[Dict] = None,
    include_av: bool = True,
) -> Dict[str, Any]:
    """
    Draft an internal ops/catering sheet grouping sessions by room with
    headcount, AV, and catering notes derived from activity data.
    """
    headers = schedule_headers or {}
    token = headers.get("Authorization", "")

    evt = _fetch_event(event_id)
    activities = _fetch_activities(event_id, token, headers)

    if not evt and not activities:
        return {
            "success": False,
            "error": f"No event or activities found for event_id={event_id}",
            "event_id": event_id,
        }

    customer_name = evt.get("customer_name") or "Unknown Customer"
    event_name    = evt.get("event_name") or "Executive Briefing"
    start_ms      = evt.get("start_time_ms")
    event_date    = _epoch_ms_to_date(start_ms) if start_ms else "TBD"
    num_attendees = evt.get("num_attendees") or ""

    # Group activities by room
    rooms: Dict[str, List[Dict]] = {}
    for act in activities:
        room = act.get("room_name") or "Unassigned"
        rooms.setdefault(room, []).append(act)

    lines = [
        "CATERING & SETUP SHEET",
        "═" * 48,
        f"Event:     {event_name}",
        f"Customer:  {customer_name}",
        f"Date:      {event_date}",
    ]
    if num_attendees:
        lines.append(f"Attendees: {num_attendees}")
    lines += ["", "─" * 48]

    if not rooms:
        lines.append("No scheduled activities found.")
    else:
        for room_name, acts in rooms.items():
            lines += ["", f"ROOM: {room_name.upper()}", "─" * 40]
            for act in acts:
                title  = act.get("title") or act.get("activity_type", "Session")
                a_type = act.get("activity_type", "")
                start  = act.get("start_iso", "") or ""
                end    = act.get("end_iso", "") or ""

                time_str = f"{_fmt_iso_time(start)} – {_fmt_iso_time(end)}" if start else "Time TBD"
                lines.append(f"\n  [{time_str}]  {title}")

                # Prefer activity_type (structured signal) over title keywords (fuzzy).
                # Fall back to title if activity_type is empty/generic.
                signal_text = a_type if a_type and a_type.lower() != "session" else f"{a_type} {title}"

                catering_note = _categorize(signal_text, CATERING_RULES, CATERING_DEFAULT)
                setup_notes = list(_categorize(signal_text, SETUP_RULES, SETUP_DEFAULT)) if include_av else []

                if num_attendees:
                    setup_notes.append(f"Seats for ~{num_attendees}")

                if setup_notes:
                    lines.append(f"  Setup:    {' | '.join(setup_notes)}")
                lines.append(f"  Catering: {catering_note}")

    lines += ["", "─" * 48, "Generated by EBC AI Assistant"]
    sheet_text = "\n".join(lines)

    logger.info(
        f"Drafted catering sheet for event {event_id} — {len(activities)} activities, {len(rooms)} room(s)"
    )
    return {
        "success": True,
        "type": "catering_sheet",
        "sheet": sheet_text,
        "event_id": event_id,
        "customer_name": customer_name,
        "event_date": event_date,
        "room_count": len(rooms),
        "activity_count": len(activities),
    }
