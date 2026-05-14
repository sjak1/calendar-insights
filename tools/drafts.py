"""
Draft generation tools — confirmation emails and catering/setup sheets.
Both tools fetch live event data from OpenSearch + BriefingIQ API and return
ready-to-use text drafts. No extra LLM call needed; caller presents the draft.
"""

from datetime import datetime, timezone as _timezone
from typing import Any, Dict, List, Optional

from logging_config import get_logger

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────
# Email template — edit here to change tone/branding without code changes
# ─────────────────────────────────────────────────────────────

CONFIRMATION_EMAIL_TEMPLATE = """Dear {customer_name} Team,

We are pleased to confirm your upcoming Executive Briefing at {location_name}.

Event Details
─────────────────────────────────
Date:      {event_date}
Time:      {time_range}
Location:  {location_block}
{focus_line}{attendees_line}
Agenda Overview
─────────────────────────────────
{agenda_block}
{notes_block}
We look forward to hosting you and ensuring a productive visit. If you have any questions or need to make changes, please don't hesitate to reach out.

Warm regards,
{host_sig}
EBC Team
"""

CONFIRMATION_SUBJECT_TEMPLATE = "Confirmed: {event_name} — {event_date}"


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
    raw_visit = _deep_get(evt.get("_raw") or {}, "eventData.VISIT_INFO.data") or {}
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

def draft_confirmation_email(
    event_id: str,
    schedule_headers: Optional[Dict] = None,
    additional_notes: Optional[str] = None,
    host_name: Optional[str] = None,
    host_email: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Draft a professional event confirmation email for the customer.
    Fetches live event + activity data and returns subject + body.
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

    customer_name = evt.get("customer_name") or "Valued Customer"
    event_name    = evt.get("event_name") or "Executive Briefing"
    location_name = evt.get("location_name") or "our facility"
    address       = _stringify_address(evt.get("location_address") or "")
    visit_focus   = evt.get("visit_focus") or ""
    num_attendees = evt.get("num_attendees") or ""
    start_ms      = evt.get("start_time_ms")
    end_ms        = evt.get("end_time_ms")
    _host_name    = host_name or evt.get("host_name") or "Your EBC Host"
    _host_email   = host_email or evt.get("host_email") or ""

    event_date = _epoch_ms_to_date(start_ms) if start_ms else "TBD"
    start_time = _epoch_ms_to_time(start_ms) if start_ms else ""
    end_time   = _epoch_ms_to_time(end_ms) if end_ms else ""
    time_range = f"{start_time} – {end_time}" if start_time and end_time else start_time or "TBD"

    # Build agenda snippet (up to 6 sessions)
    agenda_lines = []
    for act in activities[:6]:
        title = act.get("title") or act.get("activity_type", "Session")
        t = _fmt_iso_time(act.get("start_iso", "") or act.get("time", ""))
        agenda_lines.append(f"  • {t + '  ' if t else ''}{title}")
    if len(activities) > 6:
        agenda_lines.append(f"  • ... and {len(activities) - 6} more session(s)")
    agenda_block = "\n".join(agenda_lines) if agenda_lines else "  • Sessions to be confirmed"

    location_block = location_name + (f"\n  {address}" if address else "")
    focus_line = f"\nVisit focus: {visit_focus}\n" if visit_focus else ""
    attendees_line = f"We are expecting {num_attendees} attendee(s) from your team.\n" if num_attendees else ""
    notes_block = f"\n{additional_notes}\n" if additional_notes else ""
    host_sig = _host_name + (f"\n{_host_email}" if _host_email else "")

    subject = CONFIRMATION_SUBJECT_TEMPLATE.format(event_name=event_name, event_date=event_date)
    body = CONFIRMATION_EMAIL_TEMPLATE.format(
        customer_name=customer_name,
        location_name=location_name,
        event_date=event_date,
        time_range=time_range,
        location_block=location_block,
        focus_line=focus_line,
        attendees_line=attendees_line,
        agenda_block=agenda_block,
        notes_block=notes_block,
        host_sig=host_sig,
    )

    to_emails = _extract_customer_emails(evt)

    logger.info(
        f"Drafted confirmation email for event {event_id} — {customer_name}, {event_date}, "
        f"{len(to_emails)} recipient(s)"
    )
    return {
        "success": True,
        "type": "confirmation_email",
        "subject": subject,
        "body": body.strip(),
        "to": to_emails,
        "from_email": _host_email,
        "event_id": event_id,
        "customer_name": customer_name,
        "event_date": event_date,
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
