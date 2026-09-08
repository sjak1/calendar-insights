"""
EBC AI Agenda Generator Tool

Generates sample agendas for Executive Briefing Center engagement requests
by fetching relevant data and using LLM to create tailored agendas.

Data sources:
- OpenSearch (events/activities indices) for meeting context, attendees,
  similar briefings, and presenter recommendations.
- Oracle DB (VW_EVENT_DOCUMENT_REPORT) for EBD document blobs only.
- Local PPTX / PDF files as EBD fallback.

Uses OpenAI Structured Outputs for consistent, typed agenda generation.

This module is the orchestrator. The parts that stand on their own live beside
it and are re-exported below, so tools.agenda_generator remains the one import
path:

    agenda_config     env-driven tunables, and the session-count arithmetic
    agenda_models     the pydantic schema the model is asked to fill in
    agenda_documents  reading the EBD, whatever format it arrived in
    agenda_prompts    building the prompt from the gathered context
    agenda_markdown   rendering the finished agenda for the chat reply

What stays here is the work that needs all of them at once: fetching meeting
context, assigning and scheduling presenters, calling the model, and the
generate_agenda entry point.
"""

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from dotenv import load_dotenv
from openai import OpenAI
from sqlalchemy import text

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import engine  # noqa: E402 — shared engine from database.py
from logging_config import get_logger  # noqa: E402
from bedrock_llm import converse as bedrock_converse  # noqa: E402
try:
    from opensearch_client import search as os_search, get_suggested_presenters  # noqa: E402
except ImportError:
    os_search = None
    get_suggested_presenters = None

# ---------------------------------------------------------------------------
# The rest of the agenda lives in sibling modules. Everything they define is
# re-exported here: tools.agenda_generator is the import path the handlers and
# the tests already use, so this file stays the one door in.
# ---------------------------------------------------------------------------
from tools.agenda_config import (  # noqa: E402,F401
    AGENDA_BEDROCK_MODEL_ID,
    AGENDA_DAY_END,
    AGENDA_DAY_START,
    AGENDA_MAX_ATTENDEES,
    AGENDA_MAX_OUTPUT_TOKENS,
    AGENDA_PROVIDER,
    AGENDA_SESSION_MAX,
    AGENDA_SESSION_MIN,
    DEFAULT_EBD_PATH,
    EBD_MAX_NOISE_RATIO,
    EBD_MIN_WORDS,
    LLM_MODEL,
    LLM_TIMEOUT_SECONDS,
    MAX_DOCUMENT_CHARS,
    _MAX_SESSIONS_PER_DAY,
    _MAX_SESSIONS_TOTAL,
    _session_count_range,
)
from tools.agenda_models import (  # noqa: E402,F401
    AgendaSession,
    AgendaTruncated,
    BackupPresenter,
    GeneratedAgenda,
    OraclePresenter,
    StrategicNotes,
    TopicPresenterSuggestion,
)
from tools.agenda_documents import (  # noqa: E402,F401
    HAS_DOCX,
    HAS_PDFPLUMBER,
    _document_suffix,
    _ebd_quality_ok,
    _extract_docx_text,
    _extract_document_text,
    _extract_pdf_text,
    _extract_plain_text,
    _fetch_ebd_from_db,
    _sniff_document_suffix,
    _truncate_document,
)
from tools.agenda_prompts import (  # noqa: E402,F401
    _build_agenda_prompt,
    _format_correction_note,
    _rank_previous_meetings,
    _strip_prompt_sections,
)
from tools.agenda_markdown import agenda_to_markdown  # noqa: E402,F401


logger = get_logger(__name__)


# Module-level OpenAI client (reused across calls)
_openai_client: Optional[OpenAI] = None


def _get_openai_client() -> OpenAI:
    """Return a singleton OpenAI client."""
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI()
    return _openai_client







# ============================================================================
# UUID TO NUMERIC ID RESOLVER
# ============================================================================

def _resolve_event_id(event_id: Optional[str]) -> Optional[str]:
    """Delegates to the shared resolver. Kept here for backward compat."""
    from tools.event_resolver import resolve_event_id
    return resolve_event_id(event_id)


# ============================================================================
# EBD SOURCE RESOLVER CHAIN
# ============================================================================

def _try_ebd_from_db(event_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Try fetching EBD from VW_EVENT_DOCUMENT_REPORT."""
    if not event_id:
        return None
    return _fetch_ebd_from_db(event_id)


def _try_ebd_from_local(ebd_path: Optional[str]) -> Optional[Dict[str, Any]]:
    """Try extracting EBD from a local file path."""
    if not ebd_path:
        return None
    ctx = _extract_ebd_context(ebd_path)
    if ctx and ctx.get("has_ebd"):
        ctx["source"] = "local_file"
        return ctx
    return None


def _try_ebd_from_url_direct(ebd_url: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return a marker dict so the LLM call passes the URL directly."""
    if not ebd_url:
        return None
    return {"has_ebd": True, "source": "ebd_url_direct", "ebd_file_url": ebd_url}


def _try_ebd_from_local_direct(
    ebd_path: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Upload local file via Files API and return a marker dict."""
    if not ebd_path or not Path(ebd_path).exists():
        return None
    try:
        client = _get_openai_client()
        with open(ebd_path, "rb") as f:
            file = client.files.create(file=f, purpose="user_data")
        return {"has_ebd": True, "source": "local_file_direct", "ebd_file_id": file.id}
    except Exception as e:
        logger.warning(f"Could not upload EBD for direct pass: {e}. Skipping direct mode.")
        return None


def _try_ebd_default(use_default: bool) -> Optional[Dict[str, Any]]:
    """Try the default test EBD file."""
    if not use_default or not DEFAULT_EBD_PATH or not Path(DEFAULT_EBD_PATH).exists():
        return None
    ctx = _extract_ebd_context(DEFAULT_EBD_PATH)
    if ctx and ctx.get("has_ebd"):
        ctx["source"] = "default_test_file"
        return ctx
    return None


def _resolve_ebd(
    event_id: Optional[str],
    ebd_path: Optional[str],
    ebd_url: Optional[str],
    pass_ebd_directly: bool,
    use_default_ebd: bool,
    fetch_ebd_from_db: bool,
) -> Optional[Dict[str, Any]]:
    """
    Walk an ordered chain of EBD sources. Return the first that succeeds.

    Priority: DB → direct URL → direct local upload → local extract → default.
    """
    chain = []

    if fetch_ebd_from_db:
        chain.append(("database", lambda: _try_ebd_from_db(event_id)))
    if pass_ebd_directly and ebd_url:
        chain.append(("url_direct", lambda: _try_ebd_from_url_direct(ebd_url)))
    if pass_ebd_directly and ebd_path:
        chain.append(("local_direct", lambda: _try_ebd_from_local_direct(ebd_path)))
    if ebd_path:
        chain.append(("local_file", lambda: _try_ebd_from_local(ebd_path)))
    if use_default_ebd:
        chain.append(("default", lambda: _try_ebd_default(True)))

    for name, resolver in chain:
        try:
            result = resolver()
            if result and result.get("has_ebd"):
                logger.info(f"EBD resolved via: {name}")
                result.setdefault("source", name)
                return result
        except Exception as e:
            logger.warning(f"EBD resolver '{name}' failed: {e}")

    logger.info("No EBD available — generating agenda without EBD context")
    return None


# ============================================================================
# OPENSEARCH-BASED MEETING CONTEXT
# ============================================================================

def _fetch_meeting_context(event_id: Optional[str] = None, company_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetch meeting context from OpenSearch (events + activities indices).

    Falls back to SQL if OpenSearch is unavailable.
    """
    context: Dict[str, Any] = {
        "meeting_details": None,
        "attendees": [],
        "previous_meetings": [],
        "similar_briefings": [],
        "data_source": "opensearch",
    }

    if not event_id and not company_name:
        logger.error("Either event_id or company_name must be provided")
        return context

    # --- Try OpenSearch first ---
    if os_search is not None:
        try:
            os_ctx = _fetch_meeting_context_os(event_id, company_name)
            if os_ctx.get("meeting_details"):
                return os_ctx
            logger.info("OpenSearch returned no meeting details, falling back to SQL")
        except Exception as e:
            logger.warning(f"OpenSearch context fetch failed, falling back to SQL: {e}")

    # --- SQL fallback ---
    context["data_source"] = "sql"
    return _fetch_meeting_context_sql(event_id, company_name)


def _fetch_meeting_context_os(
    event_id: Optional[str] = None, company_name: Optional[str] = None
) -> Dict[str, Any]:
    """Fetch meeting context via OpenSearch events index with fuzzy matching."""
    context: Dict[str, Any] = {
        "meeting_details": None,
        "attendees": [],
        "previous_meetings": [],
        "similar_briefings": [],
        "data_source": "opensearch",
    }

    # 1. Find the meeting — exact eventId or fuzzy company name match
    if event_id:
        query_body = {
            "query": {"term": {"eventId.keyword": event_id}},
            "size": 1,
            "_source": _EVENT_SOURCE_FIELDS,
        }
    else:
        # Search eventName first (always populated), fall back to customerName
        query_body = {
            "query": {
                "bool": {
                    "should": [
                        {"term": {"eventName.keyword": company_name}},
                        {"match": {"eventName": {"query": company_name, "fuzziness": "AUTO"}}},
                        {"term": {"eventFormData.VISIT_INFO.customerName.keyword": company_name}},
                        {"match": {"eventFormData.VISIT_INFO.customerName": {"query": company_name, "fuzziness": "AUTO"}}},
                    ],
                    "minimum_should_match": 1,
                }
            },
            "size": 1,
            "sort": [{"_score": {"order": "desc"}}, {"startTime": {"order": "desc"}}],
            "_source": _EVENT_SOURCE_FIELDS,
        }

    logger.info("Fetching meeting details from OpenSearch...")
    resp = os_search(index="events", body=query_body, size_cap=1)
    if not resp.get("success") or not resp.get("hits"):
        logger.warning(f"No meeting found in OpenSearch for {event_id or company_name}")
        return context

    hit = resp["hits"][0]["source"]
    # Rich data lives under eventFormData.VISIT_INFO (a list); take first element.
    visit = _form_section(hit, "VISIT_INFO")
    context["meeting_details"] = {
        "event_id": hit.get("eventId"),
        "company_name": visit.get("customerName"),
        "industry": visit.get("customerIndustry"),
        "account_type": visit.get("accountType"),
        "line_of_business": visit.get("lineOfBusiness"),
        "visit_focus": visit.get("visitFocus"),
        "meeting_objective": visit.get("meetingObjective"),
        "sales_plays": visit.get("salesPlay"),
        "pillars": visit.get("pillars"),
        "form_type": visit.get("formType") or visit.get("visitType"),
        "region": visit.get("region"),
        "tier": visit.get("tier"),
        "start_time_ms": hit.get("startTime"),
        # The booked window's other half. Without it the agenda is laid out
        # against AGENDA_DAY_START/END rather than the hours actually reserved,
        # which is how a briefing booked 08:30-16:30 got a 10:00-17:00 agenda.
        "end_time_ms": hit.get("endTime"),
        "timezone": hit.get("timezone"),
        "duration_days": hit.get("duration"),
        "location": _event_location(hit),
    }
    actual_event_id = hit.get("eventId")
    actual_company = visit.get("customerName") or company_name
    logger.info(f"Found meeting for: {actual_company} (via OpenSearch)")

    # 2. Attendees — from the same event document (nested arrays)
    logger.info("Extracting attendees from event document...")
    ext_attendees = _form_section_list(hit, "EXTERNAL_ATTENDEES")
    int_attendees = _form_section_list(hit, "INTERNAL_ATTENDEES")
    all_raw = [(a, "External") for a in ext_attendees]
    all_raw.extend([(a, "Internal") for a in int_attendees])

    context["total_attendee_count"] = len(all_raw)
    for att, att_type in all_raw[:AGENDA_MAX_ATTENDEES]:
        context["attendees"].append({
            "name": att.get("attendeeName") or "",
            "title": att.get("businessTitle") or "",
            "c_level": att.get("chiefOfficerTitle") or None,
            "decision_maker": bool(att.get("decisionMaker")),
            "influencer": bool(att.get("influencer")),
            "technical": bool(att.get("isTechnical")),
            "type": att_type,
            "remote": bool(att.get("isRemote")),
        })
    logger.info(f"Found {len(context['attendees'])} attendees ({context['total_attendee_count']} total)")

    # 3. Previous meetings for the same company (sorted by recency)
    if actual_company:
        logger.info(f"Fetching previous meetings for {actual_company} from OpenSearch...")
        prev_body = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"eventFormData.VISIT_INFO.customerName.keyword": actual_company}},
                    ],
                    "must_not": [{"term": {"eventId.keyword": actual_event_id}}] if actual_event_id else [],
                }
            },
            "sort": [{"startTime": {"order": "desc"}}],
            "size": 5,
            "_source": [
                "eventId", "startTime",
                "eventFormData.VISIT_INFO.visitFocus",
                "eventFormData.VISIT_INFO.salesPlay",
                "eventFormData.VISIT_INFO.pillars",
                "eventFormData.VISIT_INFO.meetingObjective",
            ],
        }
        prev_resp = os_search(index="events", body=prev_body, size_cap=5)
        if prev_resp.get("success"):
            for ph in prev_resp.get("hits", []):
                ps = ph["source"]
                pv = _form_section(ps, "VISIT_INFO")
                start_ms = ps.get("startTime")
                date_str = ""
                if isinstance(start_ms, (int, float)) and start_ms > 0:
                    from datetime import datetime, timezone
                    date_str = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
                context["previous_meetings"].append({
                    "event_id": ps.get("eventId"),
                    "date": date_str,
                    "visit_focus": pv.get("visitFocus"),
                    "sales_plays": pv.get("salesPlay"),
                    "pillars": pv.get("pillars"),
                    "objective": pv.get("meetingObjective"),
                })
        logger.info(f"Found {len(context['previous_meetings'])} previous meetings")

    # 4. Similar briefings — match on industry + visit focus via OpenSearch
    context["similar_briefings"] = _fetch_similar_briefings_os(
        context["meeting_details"], actual_company
    )

    return context


# Source fields we request from the events index
_EVENT_SOURCE_FIELDS = [
    # endTime closes the booked window. Without it the agenda is laid out
    # against the AGENDA_DAY_START/END defaults no matter what hours the room
    # is actually reserved for.
    "eventId", "eventName", "startTime", "endTime", "timezone", "duration",
    "eventFormData.VISIT_INFO",
    "eventFormData.EXTERNAL_ATTENDEES",
    "eventFormData.INTERNAL_ATTENDEES",
    "status.stateName",
    "location.data",
]


def _deep_get(obj: Any, dotted_path: str) -> Any:
    """Traverse nested dicts/lists by dotted key path (e.g. 'a.b.c')."""
    for key in dotted_path.split("."):
        if isinstance(obj, list):
            obj = obj[0] if obj else None
        if isinstance(obj, dict):
            obj = obj.get(key)
        else:
            return None
    return obj


def _form_section(hit: Dict[str, Any], section: str) -> Dict[str, Any]:
    """Return the first dict of an eventFormData.{section} list (or {} if absent).

    Rich form data moved from `eventData.{section}.data` (now empty) to
    `eventFormData.{section}` (a list of dicts).
    """
    val = (hit.get("eventFormData") or {}).get(section)
    if isinstance(val, list):
        return val[0] if val else {}
    if isinstance(val, dict):
        return val
    return {}


def _form_section_list(hit: Dict[str, Any], section: str) -> List[Dict[str, Any]]:
    """Return all dicts of an eventFormData.{section} list (e.g. attendees)."""
    val = (hit.get("eventFormData") or {}).get(section)
    if isinstance(val, list):
        return val
    if isinstance(val, dict):
        return [val]
    return []


def _event_location(hit: Dict[str, Any]) -> str:
    """Human-readable venue from `location.data`.

    Requested in _EVENT_SOURCE_FIELDS since forever but never read, so the
    model was asked for a `location` field with nothing to base it on and
    filled it with "Hybrid (on-site + virtual)" every time.
    """
    loc = hit.get("location")
    if isinstance(loc, list):
        loc = loc[0] if loc else None
    data = (loc or {}).get("data") if isinstance(loc, dict) else None
    if isinstance(data, list):
        data = data[0] if data else None
    if not isinstance(data, dict):
        return ""

    name = data.get("locationName") or data.get("textField1") or ""
    street = data.get("addressLine1") or data.get("textField2") or ""
    city = data.get("city") or data.get("textField4") or ""
    state = data.get("state") or data.get("textField6") or ""
    parts = [p for p in (name, street, ", ".join(x for x in (city, state) if x)) if p]
    return " — ".join(parts)


def _fetch_similar_briefings_os(
    meeting: Optional[Dict[str, Any]], exclude_company: Optional[str]
) -> List[Dict[str, Any]]:
    """Find similar briefings via OpenSearch using industry + visit focus."""
    if not meeting or os_search is None:
        return []

    industry = meeting.get("industry")
    visit_focus = meeting.get("visit_focus")
    pillars = meeting.get("pillars")
    if not industry and not visit_focus:
        return []

    # Build a should query that scores on multiple dimensions
    should_clauses: list = []
    if industry:
        should_clauses.append({"term": {"eventFormData.VISIT_INFO.customerIndustry.keyword": {"value": industry, "boost": 2}}})
    if visit_focus:
        should_clauses.append({"match": {"eventFormData.VISIT_INFO.visitFocus": {"query": visit_focus, "boost": 3}}})
    if pillars:
        if isinstance(pillars, str):
            pillar_str = pillars
        elif isinstance(pillars, list):
            pillar_str = " ".join(str(p) for p in pillars)
        else:
            pillar_str = None
        if pillar_str:
            should_clauses.append({"match": {"eventFormData.VISIT_INFO.pillars": {"query": pillar_str, "boost": 1}}})

    must_not = []
    if exclude_company:
        must_not.append({"term": {"eventFormData.VISIT_INFO.customerName.keyword": exclude_company}})

    body = {
        "query": {
            "bool": {
                "should": should_clauses,
                "must_not": must_not,
                "minimum_should_match": 1,
            }
        },
        "size": 5,
        "sort": [{"_score": {"order": "desc"}}, {"startTime": {"order": "desc", "unmapped_type": "long"}}],
        "_source": [
            "eventFormData.VISIT_INFO.customerName",
            "eventFormData.VISIT_INFO.customerIndustry",
            "eventFormData.VISIT_INFO.visitFocus",
            "eventFormData.VISIT_INFO.salesPlay",
            "eventFormData.VISIT_INFO.pillars",
        ],
    }

    logger.info(f"Fetching similar briefings from OpenSearch (industry={industry}, focus={visit_focus})...")
    resp = os_search(index="events", body=body, size_cap=5)
    results = []
    if resp.get("success"):
        seen = set()
        for h in resp.get("hits", []):
            sv = _form_section(h["source"], "VISIT_INFO")
            co = sv.get("customerName", "")
            if co in seen:
                continue
            seen.add(co)
            results.append({
                "company": co,
                "industry": sv.get("customerIndustry"),
                "visit_focus": sv.get("visitFocus"),
                "sales_plays": sv.get("salesPlay"),
                "pillars": sv.get("pillars"),
                "relevance_score": h.get("score", 0),
            })
    else:
        logger.warning(f"Similar briefings query failed: {resp.get('error', 'unknown error')}")
    logger.info(f"Found {len(results)} similar briefings via OpenSearch")
    return results


def _fetch_meeting_context_sql(
    event_id: Optional[str] = None, company_name: Optional[str] = None
) -> Dict[str, Any]:
    """SQL fallback for meeting context (original implementation)."""
    context: Dict[str, Any] = {
        "meeting_details": None,
        "attendees": [],
        "previous_meetings": [],
        "similar_briefings": [],
        "data_source": "sql",
    }

    with engine.connect() as conn:
        if event_id:
            where_clause = "EVENTID = :event_id"
            params: dict = {"event_id": event_id}
            order_by = "DATE '1970-01-01' + (STARTDATEMS/1000)/86400 DESC"
        elif company_name:
            exact_name = company_name.lower().strip()
            where_clause = "LOWER(CUSTOMERNAME) = :exact_name OR LOWER(CUSTOMERNAME) LIKE :company_pattern"
            params = {"exact_name": exact_name, "company_pattern": f"%{exact_name}%"}
            order_by = """CASE WHEN LOWER(CUSTOMERNAME) = :exact_name THEN 0 ELSE 1 END,
                CASE WHEN CUSTOMERINDUSTRY IS NOT NULL THEN 0 ELSE 1 END,
                CASE WHEN VISITFOCUS IS NOT NULL THEN 0 ELSE 1 END,
                DATE '1970-01-01' + (STARTDATEMS/1000)/86400 DESC"""
        else:
            return context

        meeting_query = text(f"""
            SELECT EVENTID, CUSTOMERNAME, CUSTOMERINDUSTRY, ACCOUNTTYPE,
                   LINEOFBUSINESS, VISITFOCUS, MEETINGOBJECTIVE, SALESPLAY,
                   PILLARS, FORMTYPE, REGION, TIER, STARTDATEMS
            FROM VW_OPERATIONS_REPORT
            WHERE {where_clause}
            ORDER BY {order_by}
            FETCH FIRST 1 ROW ONLY
        """)
        row = conn.execute(meeting_query, params).fetchone()
        if not row:
            logger.warning("No meeting found (SQL fallback)")
            return context

        context["meeting_details"] = {
            "event_id": row[0], "company_name": row[1], "industry": row[2],
            "account_type": _parse_json_field(row[3]), "line_of_business": row[4],
            "visit_focus": row[5], "meeting_objective": row[6],
            "sales_plays": _parse_json_field(row[7]), "pillars": _parse_json_field(row[8]),
            "form_type": row[9], "region": row[10], "tier": row[11],
            "start_time_ms": int(row[12]) if row[12] is not None else None,
        }
        actual_company = row[1]
        actual_event_id = row[0]

        # Attendees
        count_q = text("SELECT COUNT(*) FROM VW_ATTENDEE_REPORT WHERE EVENTID = :event_id")
        total_attendees = conn.execute(count_q, {"event_id": actual_event_id}).fetchone()[0]
        att_q = text(f"""
            SELECT FIRSTNAME || ' ' || LASTNAME, BUSINESSTITLE, CHIEFOFFICERTITLE,
                   DECISIONMAKER, INFLUENCER, ISTECHNICAL, ATTENDEETYPE, ISREMOTE
            FROM VW_ATTENDEE_REPORT WHERE EVENTID = :event_id
            AND ROWNUM <= {AGENDA_MAX_ATTENDEES}
        """)
        for r in conn.execute(att_q, {"event_id": actual_event_id}):
            context["attendees"].append({
                "name": r[0], "title": r[1], "c_level": r[2],
                "decision_maker": r[3] == "Yes", "influencer": r[4] == "Yes",
                "technical": r[5] == "Yes", "type": r[6], "remote": r[7] == "Yes",
            })
        context["total_attendee_count"] = total_attendees

        # Previous meetings
        prev_q = text("""
            SELECT DISTINCT EVENTID,
                   TO_CHAR(DATE '1970-01-01' + (STARTDATEMS/1000)/86400, 'YYYY-MM-DD'),
                   VISITFOCUS, SALESPLAY, PILLARS, MEETINGOBJECTIVE
            FROM VW_OPERATIONS_REPORT
            WHERE CUSTOMERNAME = :company_name AND EVENTID != :event_id
            ORDER BY 2 DESC FETCH FIRST 5 ROWS ONLY
        """)
        for r in conn.execute(prev_q, {"company_name": actual_company, "event_id": actual_event_id}):
            context["previous_meetings"].append({
                "event_id": r[0], "date": r[1], "visit_focus": r[2],
                "sales_plays": _parse_json_field(r[3]), "pillars": _parse_json_field(r[4]),
                "objective": r[5],
            })

        # Similar briefings
        industry = context["meeting_details"]["industry"]
        if industry:
            sim_q = text("""
                SELECT DISTINCT CUSTOMERNAME, CUSTOMERINDUSTRY, VISITFOCUS, SALESPLAY, PILLARS
                FROM VW_OPERATIONS_REPORT
                WHERE CUSTOMERINDUSTRY = :industry AND CUSTOMERNAME != :company_name
                AND ROWNUM <= 5
            """)
            for r in conn.execute(sim_q, {"industry": industry, "company_name": actual_company}):
                context["similar_briefings"].append({
                    "company": r[0], "industry": r[1], "visit_focus": r[2],
                    "sales_plays": _parse_json_field(r[3]), "pillars": _parse_json_field(r[4]),
                })

    return context


def _parse_json_field(value: str) -> Any:
    """Parse a field that might be JSON (array or object) or plain string."""
    if value is None:
        return None
    if isinstance(value, str) and value.strip()[:1] in ("[", "{"):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, IndexError):
            return value
    return value


def _extract_ebd_context(ebd_path: str) -> Dict[str, Any]:
    """
    Extract context from an EBD file (PPTX, PDF, DOCX or plain text).
    
    Args:
        ebd_path: Path to the EBD file
        
    Returns:
        Dict with extracted EBD fields
    """
    logger.info(f"Extracting EBD content from: {ebd_path}")
    
    ebd_context = {
        "raw_text": "",
        "has_ebd": False,
    }
    
    if not ebd_path or not Path(ebd_path).exists():
        logger.warning(f"EBD file not found: {ebd_path}")
        return ebd_context
    
    try:
        suffix = _sniff_document_suffix(ebd_path) or _document_suffix(ebd_path)
        if not suffix:
            logger.warning(f"EBD is in a format we cannot read: {ebd_path}")
            return ebd_context

        extracted_text, extras = _extract_document_text(ebd_path, suffix)
        if extracted_text:
            ebd_context["raw_text"] = _truncate_document(extracted_text)
            ebd_context["has_ebd"] = True
            ebd_context.update(extras)

            detail = (
                f": {extras['slide_count']} slides, {extras['table_count']} tables"
                if extras else ""
            )
            logger.info(
                f"Extracted {len(extracted_text)} chars from "
                f"{suffix.lstrip('.').upper()}{detail}"
            )

    except Exception as e:
        logger.error(f"Error extracting EBD: {e}", exc_info=True)

    return ebd_context


def _event_timezone(meeting: Dict[str, Any]):
    """The event's own tzinfo, falling back to UTC rather than a fixed region."""
    from datetime import timezone as _tz

    event_tz = meeting.get("timezone")
    if event_tz:
        try:
            from zoneinfo import ZoneInfo as _ZI

            return _ZI(str(event_tz))
        except Exception:
            logger.debug(f"Unknown event timezone '{event_tz}', using UTC")
    return _tz.utc


def _briefing_window(meeting: Dict[str, Any], day_index: int = 1):
    """The hours actually booked for day `day_index`, as (start_ms, end_ms, tz).

    This is the canvas the agenda has to fit. Returns (None, None, tz) when the
    event carries no usable window, in which case the caller falls back to the
    AGENDA_DAY_START/END defaults.

    A "usable" window excludes the placeholder spans the data is full of — some
    events are stored as 07:00-20:00 or a flat 24 hours, which is a booking
    system default rather than a briefing that genuinely runs thirteen hours.
    Laying an agenda out across one of those is no better than the env default,
    so we do not pretend otherwise.
    """
    tz_obj = _event_timezone(meeting)
    start_ms = meeting.get("start_time_ms")
    end_ms = meeting.get("end_time_ms")
    if not start_ms or not end_ms or end_ms <= start_ms:
        return None, None, tz_obj

    try:
        from datetime import datetime as _dt, timedelta as _td

        start_dt = _dt.fromtimestamp(start_ms / 1000, tz=tz_obj)
        end_dt = _dt.fromtimestamp(end_ms / 1000, tz=tz_obj)

        # Multi-day: each day repeats day 1's clock hours.
        if day_index > 1:
            shift = _td(days=day_index - 1)
            start_dt, end_dt = start_dt + shift, end_dt + shift

        # A single day's worth of hours only. Multi-day events store the whole
        # span end-to-end, so clamp to day one's close before measuring.
        if (end_dt - start_dt) > _td(hours=14):
            end_dt = start_dt.replace(hour=17, minute=0, second=0, microsecond=0)
            if end_dt <= start_dt:
                return None, None, tz_obj

        hours = (end_dt - start_dt).total_seconds() / 3600
        # >= 13, not > 13: the canonical placeholder in this data is 07:00-20:00,
        # which is exactly 13 hours and slipped through the strict comparison —
        # so the very span this guard names was the one it let past.
        if hours < 1 or hours >= 13:
            logger.info(f"Event window looks like a placeholder ({hours:.1f}h) — using day defaults")
            return None, None, tz_obj

        return int(start_dt.timestamp() * 1000), int(end_dt.timestamp() * 1000), tz_obj
    except Exception as exc:
        logger.warning(f"Could not derive briefing window: {exc}")
        return None, None, tz_obj


def _fallback_window(meeting: Dict[str, Any], day_index: int = 1):
    """AGENDA_DAY_START/END on the event's own date — used when the event has no
    usable booked window. Still anchored to the real date and timezone, so the
    scheduler and the availability lookup are talking about the same day."""
    from datetime import datetime as _dt, timedelta as _td

    tz_obj = _event_timezone(meeting)
    start_ms = meeting.get("start_time_ms")
    day_start_min = _parse_clock(AGENDA_DAY_START) or 600
    day_end_min = _parse_clock(AGENDA_DAY_END) or 1020

    base = (
        _dt.fromtimestamp(start_ms / 1000, tz=tz_obj)
        if start_ms
        else _dt.now(tz=tz_obj)
    ) + _td(days=day_index - 1)
    midnight = base.replace(hour=0, minute=0, second=0, microsecond=0)
    start = midnight + _td(minutes=day_start_min)
    end = midnight + _td(minutes=day_end_min)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000), tz_obj


def _schedule_summary(meeting: Dict[str, Any], day_index: int = 1) -> Dict[str, Any]:
    """Human-readable description of the day the agenda has to fit into.

    Used both to tell the model what canvas it is writing for and to give the
    scheduler its bounds, so the two can never disagree.
    """
    from datetime import datetime as _dt

    start_ms, end_ms, tz_obj = _briefing_window(meeting, day_index)
    booked = start_ms is not None
    if not booked:
        start_ms, end_ms, tz_obj = _fallback_window(meeting, day_index)

    start_dt = _dt.fromtimestamp(start_ms / 1000, tz=tz_obj)
    end_dt = _dt.fromtimestamp(end_ms / 1000, tz=tz_obj)
    fmt = lambda d: d.strftime("%I:%M %p").lstrip("0")  # noqa: E731

    return {
        "start_ms": start_ms,
        "end_ms": end_ms,
        "tz": tz_obj,
        "booked": booked,
        "date": start_dt.strftime("%A, %d %B %Y"),
        "label": f"{fmt(start_dt)} - {fmt(end_dt)} {start_dt.tzname() or ''}".strip()
        + ("" if booked else " (no booked hours on file — using default briefing hours)"),
        "minutes": int((end_ms - start_ms) / 60000),
    }


# A briefing runs a handful of days; anything past this is a data error, and
# each extra day is another availability query.
_MAX_AVAILABILITY_DAYS = 7


def _availability_windows(meeting: Dict[str, Any], days: int = 1):
    """One (start_ms, end_ms) per briefing day, in the EVENT's own timezone.

    Day N is day one's date shifted by N-1, matching how `_briefing_window`
    lays a multi-day briefing out. Each entry spans that whole calendar day, so
    an overlap query against it also catches a commitment that starts before
    the briefing hours and runs into them.

    Falls back to UTC rather than a hardcoded region, so non-US briefings get
    the right day. Returns [] when the event has no start time.
    """
    start_time_ms = meeting.get("start_time_ms")
    if not start_time_ms:
        return []
    try:
        from datetime import timezone as _tz
        from datetime import datetime as _dt, timedelta as _td, time as _t

        tz_obj = _tz.utc
        event_tz = meeting.get("timezone")
        if event_tz:
            try:
                from zoneinfo import ZoneInfo as _ZI

                tz_obj = _ZI(str(event_tz))
            except Exception:
                logger.debug(f"Unknown event timezone '{event_tz}', using UTC")
        event_dt = _dt.fromtimestamp(start_time_ms / 1000, tz=tz_obj)
        day_one = event_dt.date()
        out = []
        for offset in range(max(1, days)):
            # Rebuild each boundary from its own calendar date rather than
            # adding 24h to the previous one: a DST change inside the briefing
            # makes a day 23 or 25 hours long, and fixed steps drift off it.
            d_start = _dt.combine(day_one + _td(days=offset), _t(0, 0, 0), tzinfo=tz_obj)
            d_end = _dt.combine(day_one + _td(days=offset + 1), _t(0, 0, 0), tzinfo=tz_obj)
            out.append((int(d_start.timestamp() * 1000), int(d_end.timestamp() * 1000)))
        return out
    except Exception:
        return []


def _availability_window(meeting: Dict[str, Any]):
    """Day one's window alone — the window the *ranking* signal is scored over.

    Deliberately not widened to the whole briefing. `get_suggested_presenters`
    collapses whatever window it is given into one available/unavailable flag
    and sorts free candidates first; across four days almost every senior
    presenter has something booked, so a briefing-wide window here would mark
    the entire pool unavailable and flatten the sort into noise.

    The check that actually places people is `_is_free` in the scheduler, which
    tests one slot at a time against the full multi-day busy map built below.
    """
    windows = _availability_windows(meeting, 1)
    return windows[0] if windows else (None, None)


def _assign_presenters_by_topic(
    sessions: List[Any],
    context: Dict[str, Any],
    schedule_headers: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Phase two — match a presenter to each session's own topic.

    The pool fetched before generation is scoped by event/customer/industry
    only, because at that point no session exists yet to have a topic. That
    means the strongest ranking signals — match tier and depth on the matched
    topic — sit idle, and the model assigns names from a pool on its own
    judgement. This runs after generation, when each session finally has a
    subject, and asks the ranking the question it is actually good at: who is
    the best person for THIS topic.

    Conservative by design. It records a suggestion per session and only
    overrides the model's choice when the topic match is strong (exact or
    related) and the person is not already booked. A weak match, an
    unavailable expert, or any error leaves the generated agenda untouched.

    Returns a summary for logging/telemetry; sessions are annotated in place.
    """
    if not sessions:
        return {"checked": 0, "matched": 0, "reassigned": 0}

    topics = []
    for sess in sessions:
        t = (getattr(sess, "topic", None) or "").strip()
        if t and t not in topics:
            topics.append(t)
    if not topics:
        logger.info("Per-session presenters: no session carried a topic; skipped")
        return {"checked": 0, "matched": 0, "reassigned": 0}

    meeting = context.get("meeting_details") or {}
    start_ms, end_ms = _availability_window(meeting)

    def lookup(topic: str):
        kwargs: Dict[str, Any] = {"topic": topic, "limit": 3}
        if start_ms and end_ms:
            kwargs["check_start_utc_ms"] = start_ms
            kwargs["check_end_utc_ms"] = end_ms
        if schedule_headers:
            from tools.handlers import _bearer_token

            kwargs["api_token"] = _bearer_token(schedule_headers)
            kwargs["api_headers"] = schedule_headers
        try:
            r = get_suggested_presenters(**kwargs)
            return topic, (r.get("suggested_presenters") or []) if r.get("success") else []
        except Exception as exc:
            logger.warning(f"Per-session presenter lookup failed for {topic!r}: {exc}")
            return topic, []

    # One lookup per DISTINCT topic, run concurrently: they are independent and
    # I/O-bound, so N topics cost roughly one round trip rather than N.
    by_topic: Dict[str, List[Dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=min(6, len(topics))) as pool:
        for topic, people in pool.map(lookup, topics):
            by_topic[topic] = people

    # Tiers strong enough to overrule the model's own assignment.
    STRONG = {"exact match", "related topic"}
    matched = reassigned = 0
    # Sessions each person has been GIVEN by this pass. Sessions are matched
    # independently, so without this the same expert wins every slot their
    # topic covers and ends up presenting the whole day — the model's spread
    # of names is worth keeping unless a specific session has a better expert.
    assigned_here: Dict[str, int] = {}
    _MAX_REASSIGNS_PER_PERSON = 2

    def _names_match(name: str, presenter_field: str) -> bool:
        # The presenter field is "name and title" prose, so compare on word
        # boundaries — a bare substring test makes "Dan" match "Danielle".
        if not name or not presenter_field:
            return False
        return re.search(rf"\b{re.escape(name)}\b", presenter_field, re.IGNORECASE) is not None

    for sess in sessions:
        topic = (getattr(sess, "topic", None) or "").strip()
        if not topic:
            continue
        people = by_topic.get(topic) or []
        if not people:
            continue
        matched += 1
        best = people[0]
        sess.topic_presenter_suggestion = TopicPresenterSuggestion(
            presenter_name=best.get("presenter_name"),
            title=best.get("title"),
            match_tier=best.get("match_tier"),
            matched_topic=best.get("matched_topic"),
            available=best.get("available"),
            reason=best.get("reason"),
            revenue_delta=best.get("revenue_delta"),
            revenue_events=best.get("revenue_events"),
            revenue_note=best.get("revenue_note"),
        )
        # An unfilled slot is a different decision from a filled one. When the
        # session has no real presenter — TBD, blank, or a placeholder — a
        # booked expert still beats TBD: the reader gets a name plus the
        # conflict, instead of nothing. Only when a slot already has someone do
        # we insist the replacement be free, since displacing a named presenter
        # with someone unavailable would be a downgrade.
        current = (sess.presenter or "").strip()
        unfilled = current.upper() in {"", "TBD", "TBA", "N/A", "-"}

        # Reassign to the strongest candidate. limit=3 supplies the alternates.
        for cand in people:
            name = cand.get("presenter_name") or ""
            strong = cand.get("match_tier") in STRONG
            # available is only set when a window was given; without one there
            # is nothing to check, so topic strength alone decides.
            free = cand.get("available") is not False
            if not (strong and name) or not (free or unfilled):
                continue
            if _names_match(name, sess.presenter or ""):
                break  # the model already picked this expert — leave it
            if assigned_here.get(name.lower(), 0) >= _MAX_REASSIGNS_PER_PERSON:
                continue  # spread the day; try the next-ranked expert
            sess.presenter_before_topic_match = sess.presenter
            title = (cand.get("title") or "").strip()
            sess.presenter = f"{name} — {title}" if title else name
            assigned_here[name.lower()] = assigned_here.get(name.lower(), 0) + 1
            reassigned += 1
            break

    # A plain-language account of every pick, so the answer can show its
    # working rather than asserting a name. One entry per distinct topic, in
    # the ranking's own words plus the revenue caveat where there is one.
    rationale = []
    for topic in topics:
        people = by_topic.get(topic) or []
        if not people:
            rationale.append({
                "topic": topic,
                "chosen": None,
                "why": "nobody in the history has presented this topic",
            })
            continue
        best = people[0]
        entry = {
            "topic": topic,
            "chosen": best.get("presenter_name"),
            "why": best.get("reason") or "",
            "available": best.get("available"),
            "runners_up": [
                {"presenter_name": c.get("presenter_name"), "why": c.get("reason") or ""}
                for c in people[1:3]
            ],
        }
        if best.get("revenue_note"):
            entry["revenue"] = best["revenue_note"]
        rationale.append(entry)

    logger.info(
        f"Per-session presenters: {len(topics)} topic(s) looked up, "
        f"{matched} session(s) matched, {reassigned} reassigned"
    )
    return {
        "checked": len(topics),
        "matched": matched,
        "reassigned": reassigned,
        "rationale": rationale,
        # The full ranked pool per topic. The scheduler needs it for alternates:
        # knowing only the winner leaves it nothing to fall back to when that
        # person turns out to be busy at the hour the session lands on.
        "by_topic": by_topic,
        "guidance": (
            "ALWAYS end the agenda with a short 'Why these presenters' section — "
            "do not wait to be asked. A staffing choice a reader cannot check is a "
            "choice they cannot trust, and the whole point of ranking on evidence "
            "is that the evidence can be shown.\n"
            "Keep it to ONE line per presenter: name, the topic they matched, and "
            "the depth that won it (e.g. 'Naveen Sajja — Commerce Cloud: 2 sessions "
            "on it, 1 accepted'). Flag anyone unavailable on the day. Do not list "
            "runners-up, do not repeat the full reason string, and do not restate "
            "the agenda — the table above already carries the assignments.\n"
            "Give runners-up and the fuller reasoning only if the user asks who "
            "else was considered.\n"
            "Revenue, where present, is deal movement at that person's briefings. "
            "Mention it only where it distinguishes candidates, and never without "
            "its caveat: a briefing has several presenters and one figure, so the "
            "credit is shared rather than earned.\n"
            "Where 'chosen' is null nobody has presented that topic — say so "
            "plainly rather than omitting the line."
        ),
    }


def _get_presenter_recommendations(
    context: Dict[str, Any],
    schedule_headers: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch presenter recommendations to guide agenda generation.

    We combine multiple scopes so agenda generation has useful names even when
    the current event has little or no presenter history.
    """
    if get_suggested_presenters is None:
        return []

    meeting = context.get("meeting_details") or {}
    if not meeting:
        return []

    event_id = meeting.get("event_id")
    company_name = meeting.get("company_name")
    industry = meeting.get("industry")
    visit_focus = meeting.get("visit_focus")
    start_time_ms = meeting.get("start_time_ms")

    # Event-day availability window, in the event's own timezone.
    check_start_ms, check_end_ms = _availability_window(meeting)

    # ONE ranked call, not three merged. get_suggested_presenters already
    # returns candidates in ranked order; the agenda used to make three scoped
    # calls and re-sort the union, which meant a second ranking sitting on top
    # of the real one and drifting from it. Scopes are tried most-specific
    # first and the first that returns anything wins — the same intent the
    # merge had, without a competing sort.
    scopes = [
        ("same_event", {"event_id": event_id}),
        ("same_company", {"customer_name": company_name}),
        ("industry", {"industry": industry}),
    ]

    ranked: List[Dict[str, Any]] = []
    source = ""
    for label, scope_kwargs in scopes:
        kwargs = {k: v for k, v in scope_kwargs.items() if v}
        if not kwargs:
            continue
        kwargs["limit"] = 8
        if check_start_ms and check_end_ms:
            kwargs["check_start_utc_ms"] = check_start_ms
            kwargs["check_end_utc_ms"] = check_end_ms
        if schedule_headers:
            # Case-tolerant: HTTP/2 lowercases header names, so a browser sends
            # `authorization` and a plain .get("Authorization") is empty. Use
            # the shared helper — inlining a .get() here is exactly the bug it
            # replaced.
            from tools.handlers import _bearer_token

            kwargs["api_token"] = _bearer_token(schedule_headers)
            kwargs["api_headers"] = schedule_headers
        try:
            result = get_suggested_presenters(**kwargs)
        except Exception as e:
            logger.warning(f"Presenter suggestions failed for scope '{label}': {e}")
            continue
        if result.get("success") and result.get("suggested_presenters"):
            ranked = result["suggested_presenters"]
            source = label
            logger.info(f"Presenter pool from scope '{label}': {len(ranked)} candidates")
            break

    if not ranked:
        return []

    # Exclude anyone attending as a customer — they are in the room, not
    # presenting to it.
    attendee_names = {
        a.get("name", "").strip().lower()
        for a in context.get("attendees", [])
        if a.get("type") == "External"
    }

    recommendations = []
    for item in ranked:
        name_lower = (item.get("presenter_name") or "").strip().lower()
        if name_lower in attendee_names:
            logger.info(
                f"Excluding presenter rec {item.get('presenter_name')!r} — is an external attendee"
            )
            continue
        conflict_note = ""
        available = item.get("available")
        if available is False:
            slots = ", ".join(
                c.get("time", "") for c in (item.get("conflicts") or [])[:2] if c.get("time")
            )
            conflict_note = (
                f" ⚠️ May be double-booked on event day ({slots})"
                if slots
                else " ⚠️ May be double-booked on event day"
            )
        recommendations.append(
            {
                "presenter_name": item.get("presenter_name"),
                "presenter_id": item.get("presenter_id", ""),
                "title": item.get("title", ""),
                "session_count": item.get("session_count", 0),
                "event_count": item.get("event_count", 0),
                "match_tier": item.get("match_tier", ""),
                "recency_weighted_sessions": item.get("recency_weighted_sessions", 0),
                "accepted_count": item.get("accepted_count", 0),
                "source": source,
                "sample_topic": item.get("sample_topic"),
                "sample_event_id": item.get("sample_event_id"),
                "available": available,
                "conflicts": (item.get("conflicts") or [])[:2],
                "reason": f"Scope: {source}. {item.get('reason', '')}{conflict_note}",
            }
        )

    return recommendations


_TIME_RE = re.compile(r"(\d{1,2}:\d{2}\s*[APap]\.?[Mm]\.?)")


def _parse_clock(value: str) -> Optional[int]:
    """Parse a clock string like '10:00 AM' into minutes-since-midnight, or None."""
    if not value:
        return None
    cleaned = value.strip().upper().replace(".", "").replace(" ", "")
    try:
        from datetime import datetime as _dt
        parsed = _dt.strptime(cleaned, "%I:%M%p")
        return parsed.hour * 60 + parsed.minute
    except ValueError:
        return None


def _parse_time_slot(slot: str) -> Optional[tuple]:
    """Parse 'H:MM AM - H:MM PM' into (start_minutes, end_minutes), or None."""
    if not slot:
        return None
    times = _TIME_RE.findall(slot)
    if len(times) < 2:
        return None
    start = _parse_clock(times[0])
    end = _parse_clock(times[1])
    if start is None or end is None:
        return None
    return start, end


def _validate_agenda_sessions(
    agenda: "GeneratedAgenda",
    expected_days: int = 1,
    meeting: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """
    Deterministically check session times. Returns a list of human-readable
    issues (empty list = agenda is well-formed).

    Checks (per day): parseable slots, end-after-start, within the day window,
    no overlap with the previous session on the same day, and a lunch break
    present. For multi-day events, also checks every expected day has sessions.

    The window is the event's BOOKED hours when it has them, falling back to
    AGENDA_DAY_START/END otherwise. Validating against the env defaults while
    the briefing actually runs 08:30-16:30 checks the agenda against a day that
    does not exist — it passed agendas that overran the booking and flagged
    correct ones that started before 10am.
    """
    issues: List[str] = []
    window_label = f"{AGENDA_DAY_START} - {AGENDA_DAY_END}"
    day_start = _parse_clock(AGENDA_DAY_START)
    day_end = _parse_clock(AGENDA_DAY_END)
    if meeting:
        sched = _schedule_summary(meeting)
        from datetime import datetime as _dt

        w_start = _dt.fromtimestamp(sched["start_ms"] / 1000, tz=sched["tz"])
        w_end = _dt.fromtimestamp(sched["end_ms"] / 1000, tz=sched["tz"])
        day_start = w_start.hour * 60 + w_start.minute
        day_end = w_end.hour * 60 + w_end.minute
        window_label = sched["label"]

    # Group sessions by day, preserving order within each day
    by_day: Dict[int, list] = {}
    for i, s in enumerate(agenda.sessions, 1):
        day = s.day if isinstance(getattr(s, "day", None), int) and s.day >= 1 else 1
        by_day.setdefault(day, []).append((i, s))

    for day in sorted(by_day):
        day_label = f" on day {day}" if expected_days > 1 or len(by_day) > 1 else ""
        prev_end: Optional[int] = None
        for i, s in by_day[day]:
            label = f"Session {i} ('{s.title}'){day_label}"
            parsed = _parse_time_slot(s.time_slot)
            if parsed is None:
                issues.append(f"{label} has an unparseable time_slot '{s.time_slot}'. Use format 'H:MM AM - H:MM PM'.")
                continue
            start, end = parsed
            if end <= start:
                issues.append(f"{label} ends at or before it starts ({s.time_slot}).")
            if day_start is not None and start < day_start:
                issues.append(f"{label} starts before the day window ({window_label}).")
            if day_end is not None and end > day_end:
                issues.append(f"{label} ends after the day window ({window_label}).")
            if prev_end is not None and start < prev_end:
                issues.append(f"{label} overlaps the previous session (it starts before the prior session ends).")
            prev_end = end

        if not any("lunch" in (s.title or "").lower() for _, s in by_day[day]):
            issues.append(
                f"No lunch break is scheduled{day_label or ' '}. Add a lunch session within {window_label}."
            )

    # Multi-day coverage: every expected day must have sessions
    for day in range(1, max(1, expected_days) + 1):
        if day not in by_day:
            issues.append(
                f"This is a {expected_days}-day briefing but day {day} has no sessions. "
                f"Create sessions for every day (set the day field 1..{expected_days})."
            )

    return issues


def _schedule_agenda_sessions(
    agenda: "GeneratedAgenda",
    context: Dict[str, Any],
    by_topic: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """Assign real clock times, scheduling around presenter availability.

    This is the step that makes availability an input rather than a footnote.
    Before it existed the model wrote `time_slot` against env defaults and the
    availability check ran afterwards, producing a warning nobody acted on — so
    an agenda could be, and routinely was, staffed with people already booked
    and laid out across hours the room was not reserved for.

    Sessions are annotated in place. Returns a summary for logging/telemetry.
    """
    from tools.agenda_scheduler import SessionSpec, layout

    meeting = context.get("meeting_details") or {}
    sessions = list(agenda.sessions or [])
    if not sessions:
        return {"scheduled": 0}

    by_topic = by_topic or {}

    # Every address of every candidate we might place, so one lookup per day
    # covers the whole pool.
    emails: set = set()
    for people in by_topic.values():
        for person in people:
            emails.update(e.lower() for e in (person.get("all_emails") or []) if e)
            if person.get("email"):
                emails.add(person["email"].lower())

    by_day: Dict[int, List[Any]] = {}
    for sess in sessions:
        day = sess.day if isinstance(getattr(sess, "day", None), int) and sess.day >= 1 else 1
        by_day.setdefault(day, []).append(sess)

    # A busy map covering every scheduled day, fetched one day at a time.
    #
    # This was a single lookup over day one's midnight-to-midnight window,
    # reused for the entire briefing. Since `_is_free` compares absolute
    # timestamps, a day-one booking can never overlap a day-two slot — so on a
    # four-day agenda only day one was really checked and every presenter read
    # as free on days two through four, which the finished agenda then stated
    # as though it had been verified.
    #
    # Per day rather than one wide span because the conflict query is capped at
    # _CONFLICT_SCAN_SIZE rows: widening the window multiplies the hits and
    # silently drops the ones past the cut, which reports a booked presenter as
    # free — the exact failure that check exists to prevent.
    # Capped: `by_day` keys come from model output, so a single stray `day: 40`
    # would otherwise fan out into forty OpenSearch queries.
    scheduled_days = [d for d in sorted(by_day) if d <= _MAX_AVAILABILITY_DAYS]
    all_windows = _availability_windows(meeting, max(scheduled_days) if scheduled_days else 1)
    day_lookups = [(d, all_windows[d - 1]) for d in scheduled_days if d - 1 < len(all_windows)]

    busy_map: Dict[str, List[tuple]] = {}
    checked_days: List[int] = []
    if emails and day_lookups:
        try:
            from tools.presenter_suggest import _check_presenter_conflicts

            # Sequential, deliberately. These are size-capped scans over the
            # activities index, and running the days concurrently measured
            # consistently slower than running them in order (2.2-2.6s against
            # 1.2-2.0s for four days) — four large scans contend on the cluster
            # more than they overlap. Against a ~65s agenda either is noise, so
            # the simpler and faster of the two wins.
            for day, (start_ms, end_ms) in day_lookups:
                if not start_ms or not end_ms:
                    continue
                try:
                    # Exclude this event's own activities: we are laying out THIS
                    # briefing, so its existing sessions are the thing being
                    # planned, not a competing commitment.
                    raw = _check_presenter_conflicts(
                        sorted(emails), start_ms, end_ms,
                        exclude_event_id=meeting.get("event_id"),
                    )
                except Exception as exc:
                    # One day failing must not take the rest of the briefing
                    # with it, nor let that day read as checked.
                    logger.warning(
                        f"Busy-map lookup failed for day {day}, scheduling it without one: {exc}"
                    )
                    continue

                # Only a day whose lookup actually returned counts as checked;
                # one that failed must not inherit its neighbours' coverage and
                # read as verified.
                checked_days.append(day)
                for email, entries in raw.items():
                    spans = [
                        (e["start_ms"], e["end_ms"])
                        for e in entries
                        if e.get("start_ms") and e.get("end_ms")
                    ]
                    if not spans:
                        continue
                    known = busy_map.setdefault(email, [])
                    # A booking straddling midnight comes back from both days'
                    # queries; keep one copy.
                    known.extend(s for s in spans if s not in known)
        except Exception as exc:
            logger.warning(f"Presenter busy-map lookup failed, scheduling without it: {exc}")

    checked_days.sort()
    checked_spans = [all_windows[d - 1] for d in checked_days if d - 1 < len(all_windows)]
    win_start = min((s for s, _ in checked_spans), default=None)
    win_end = max((e for _, e in checked_spans), default=None)

    total_placed = 0
    unplaced_titles: List[str] = []
    notes: List[str] = []
    conflicts = 0
    backups = 0
    windows: List[str] = []
    # Rebuilt in placement order. The scheduler may reorder a day to keep the
    # best presenter, and leaving agenda.sessions in the model's original order
    # would leave the list out of chronological sequence — times jumping
    # backwards mid-agenda, which every downstream reader treats as an overlap.
    resequenced: List[Any] = []

    day_windows: Dict[int, Dict[str, Any]] = {}

    for day in sorted(by_day):
        sched = _schedule_summary(meeting, day_index=day)
        windows.append(f"day {day}: {sched['label']}")
        day_windows[day] = {
            "start_ms": sched["start_ms"],
            "end_ms": sched["end_ms"],
            "label": sched["label"],
        }

        specs = []
        for sess in by_day[day]:
            topic = (getattr(sess, "topic", None) or "").strip()
            specs.append(
                SessionSpec(
                    title=sess.title,
                    duration_target=max(5, int(getattr(sess, "duration_minutes", 45) or 45)),
                    duration_min=getattr(sess, "duration_min_minutes", None),
                    duration_max=getattr(sess, "duration_max_minutes", None),
                    anchor=getattr(sess, "anchor", "any") or "any",
                    movable=bool(getattr(sess, "movable", True)),
                    topic=topic or None,
                    candidates=list(by_topic.get(topic) or []),
                    payload=sess,
                )
            )

        result = layout(
            specs, sched["start_ms"], sched["end_ms"], sched["tz"], busy_map
        )

        for placed in result.placed:
            sess = placed.spec.payload
            resequenced.append(sess)
            sess.time_slot = placed.time_slot
            if placed.presenter:
                name = placed.presenter.get("presenter_name") or ""
                title = (placed.presenter.get("title") or "").strip()
                if name:
                    new_presenter = f"{name} — {title}" if title else name
                    if new_presenter != (sess.presenter or "").strip():
                        sess.presenter_before_topic_match = (
                            sess.presenter_before_topic_match or sess.presenter
                        )
                    sess.presenter = new_presenter
            if placed.scheduling_note:
                notes.append(f"{sess.title}: {placed.scheduling_note}")
                # Carry the reason onto the session so the answer can explain
                # the shape of the day instead of just asserting it.
                sess.scheduling_note = placed.scheduling_note
            # The alternates the scheduler already checked are free at this
            # exact slot. Computing them and dropping them meant the one
            # question a briefing team always asks — "who else could do this?"
            # — had an answer that never left the scheduler.
            sess.backup_presenters = [
                BackupPresenter(
                    presenter_name=alt.get("presenter_name") or "",
                    title=(alt.get("title") or "").strip() or None,
                    match_tier=alt.get("match_tier"),
                    reason=alt.get("reason"),
                )
                for alt in placed.alternates
                if alt.get("presenter_name")
            ]
            backups += len(sess.backup_presenters)
            if placed.has_conflict:
                conflicts += 1
            total_placed += 1

        for spec in result.unplaced:
            unplaced_titles.append(spec.title)

    # Chronological order, days in sequence. Anything the scheduler could not
    # fit is dropped here rather than left behind with an empty time slot.
    agenda.sessions = resequenced

    logger.info(
        f"Scheduled {total_placed} session(s) across {len(by_day)} day(s); "
        f"{conflicts} unavoidable conflict(s), {len(unplaced_titles)} did not fit"
    )
    return {
        "scheduled": total_placed,
        "windows": windows,
        "moved": notes,
        "unavoidable_conflicts": conflicts,
        "backups_offered": backups,
        "did_not_fit": unplaced_titles,
        # What availability actually got checked, kept so the provenance trail
        # can state it rather than implying it. `checked_days` is the honest
        # list: a day missing from it was scheduled against an empty busy map,
        # so every presenter read as free there because nothing was looked up.
        "availability": {
            "window_start_ms": win_start,
            "window_end_ms": win_end,
            "checked_days": checked_days,
            "checked_emails": sorted(emails),
            "busy_spans_by_email": {
                email: [[int(a), int(b)] for a, b in spans]
                for email, spans in busy_map.items()
            },
            "day_windows": day_windows,
        },
        "guidance": (
            "Session times came from the event's booked hours and the presenters' "
            "real calendars, not from a template — state the date and hours as fact. "
            "Where a session carries a scheduling note, mention it once: it explains "
            "why the day is shaped as it is. If anything is listed under did_not_fit, "
            "say plainly that it was dropped for lack of time rather than omitting it. "
            "Where a session carries backup_presenters, those people were checked free "
            "at that exact slot — offer them as the fallback if the primary drops out."
        ),
    }




def _enforce_session_cap(agenda: "GeneratedAgenda") -> "GeneratedAgenda":
    """Hold the agenda to _MAX_SESSIONS_TOTAL, in place, without losing a day.

    The budget is stated in the prompt but the model treats it as advice: a
    five-day Zurich briefing was asked for 20 sessions and wrote 35. Trimming
    here means length stops depending on the model complying.

    What it must NOT do is trim the flat list. Sessions arrive in day order, so
    `sessions[:24]` takes every dropped session off the end of the briefing: a
    four-day Subaru agenda came back 7/8/8/7 and was cut to 7/8/8/1, leaving day
    four with nothing but its own kickoff — and the model's closing note then
    pointed out that day four had no lunch, having been given no chance to keep
    one. The overshoot is spread across the days, so the trim should be too.

    Sessions are taken from whichever day currently has the most, skipping the
    ones that carry a day's shape: its open, its close, its lunch, and anything
    the model pinned. Within a day the middle goes before the edges, matching
    how the scheduler's own `_fit_to_window` drops from the movable middle.
    """
    extra = len(agenda.sessions) - _MAX_SESSIONS_TOTAL
    if extra <= 0:
        return agenda

    sessions = list(agenda.sessions)

    def _day_of(sess) -> int:
        day = getattr(sess, "day", None)
        return day if isinstance(day, int) and day >= 1 else 1

    def _protected(sess) -> bool:
        return (getattr(sess, "anchor", "any") or "any") in ("open", "lunch", "close") \
            or not bool(getattr(sess, "movable", True))

    by_day: Dict[int, List[int]] = {}
    for i, sess in enumerate(sessions):
        by_day.setdefault(_day_of(sess), []).append(i)

    dropped: set = set()
    for _ in range(extra):
        # Fullest day first, counting only what is still standing. Ties break on
        # the later day so an early day is not repeatedly raided.
        candidates = sorted(
            by_day.items(),
            key=lambda kv: (-len([i for i in kv[1] if i not in dropped]), -kv[0]),
        )
        victim = None
        for _day, idxs in candidates:
            live = [i for i in idxs if i not in dropped and not _protected(sessions[i])]
            if live:
                victim = live[len(live) // 2]  # middle of the day, not its edges
                break
        if victim is None:
            # Every remaining session is an open, a close, a lunch or pinned.
            # Nothing can go without damaging a day's shape, so stop early and
            # let the scheduler's per-day fit handle the overflow.
            logger.warning(
                f"Session cap: only protected sessions remain, keeping "
                f"{len(sessions) - len(dropped)} over the {_MAX_SESSIONS_TOTAL} cap"
            )
            break
        dropped.add(victim)

    if dropped:
        kept_by_day = {
            d: len([i for i in idxs if i not in dropped]) for d, idxs in sorted(by_day.items())
        }
        logger.warning(
            f"Agenda came back with {len(sessions)} sessions, over the "
            f"{_MAX_SESSIONS_TOTAL} cap; dropped {len(dropped)} from the fullest "
            f"days, leaving {kept_by_day}"
        )
        agenda.sessions = [s for i, s in enumerate(sessions) if i not in dropped]
    return agenda


def _event_num_days(meeting: Optional[Dict[str, Any]]) -> int:
    """Number of briefing days to schedule, from the event's duration field.
    Clamped to 1..5 (longer durations are almost certainly data errors)."""
    try:
        days = int((meeting or {}).get("duration_days") or 1)
    except (TypeError, ValueError):
        days = 1
    return max(1, min(days, 5))




def _generate_agenda_with_llm(
    context: Dict[str, Any],
    ebd_context: Optional[Dict[str, Any]] = None,
    ebd_file_url: Optional[str] = None,
    ebd_file_id: Optional[str] = None,
    correction_note: Optional[str] = None,
) -> GeneratedAgenda:
    """
    Use LLM to generate a tailored agenda based on the context.

    Uses OpenAI Structured Outputs for consistent, typed responses.

    Args:
        context: Meeting context from database
        ebd_context: Optional EBD document context (extracted raw_text) for richer data
        ebd_file_url: Optional public URL of EBD doc — passed in same call as file (no separate extraction)
        ebd_file_id: Optional file_id from Files API — passed in same call as file (no separate extraction)

    When ebd_file_url or ebd_file_id is set, the doc is attached to the user message in this
    single call (one LLM call). Otherwise we use ebd_context (pre-extracted text) in the prompt.
    """
    meeting = context["meeting_details"]
    attendees = context["attendees"]
    previous = _rank_previous_meetings(context["previous_meetings"], meeting)
    similar = context["similar_briefings"]
    presenter_recommendations = context.get("presenter_recommendations", [])

    # Analyze attendee mix
    total_attendee_count = context.get("total_attendee_count", len(attendees))
    c_level_attendees = [a for a in attendees if a.get("c_level")]
    decision_makers = [a for a in attendees if a.get("decision_maker")]
    technical_attendees = [a for a in attendees if a.get("technical")]
    remote_attendees = [a for a in attendees if a.get("remote")]
    external_attendees = [a for a in attendees if a.get("type") == "External"]

    # Document: either pre-extracted text (ebd_context) or we'll pass file in same call (ebd_file_*)
    has_ebd_file = bool(ebd_file_url or ebd_file_id)
    has_ebd = has_ebd_file or (ebd_context and ebd_context.get("has_ebd"))

    ebd_section = ""
    if not has_ebd_file and ebd_context and ebd_context.get("has_ebd"):
        ebd_section = f"""

## ATTACHED DOCUMENT (extracted text — format may vary)

The following text was automatically extracted from an uploaded document
(PDF, PPTX, etc.). The structure is *not* guaranteed — mine it for any
useful facts: names, titles, dollar figures, KPIs, customer references,
challenges, attendee concerns, or meeting objectives.

Use what you find; ignore what's missing.

--- BEGIN DOCUMENT ---
{ebd_context.get('raw_text', '')}
--- END DOCUMENT ---
"""

    presenter_section = ""
    topic_vocabulary = context.get("available_topics") or []
    topics_section = ""
    if topic_vocabulary:
        topics_section = (
            "\n\n## AVAILABLE TOPICS\n\n"
            "Tag each content session with the ONE topic below that best describes it, "
            "copied exactly, in the session's `topic` field. These are the only topics "
            "this tenant has presenter history for, so the tag is what lets the right "
            "expert be matched to the session. Use null for welcome slots, breaks and "
            "closes, and whenever nothing here genuinely fits — never invent a topic.\n\n"
            + ", ".join(topic_vocabulary)
        )

    # Emitted whenever EITHER half exists: the topic vocabulary must reach the
    # prompt even when no presenter history matched — an event with no history
    # is exactly the case where per-session topic matching is the only way a
    # presenter gets picked at all.
    if presenter_recommendations or topics_section:
        rec_block = (
            json.dumps(presenter_recommendations, indent=2)
            if presenter_recommendations
            else "(no historical matches — leave presenters as TBD unless the document names them)"
        )
        presenter_section = f"""

## PRESENTER RECOMMENDATIONS

Use these as agenda-generation hints. These names come from matched historical
activities in the same event, same company, or same topic/industry.
Only use them when they fit the session. If a presenter title is unknown, keep
the title as TBD instead of inventing one.

{rec_block}
{topics_section}
"""

    # Multi-day: how many briefing days to schedule (from the event's duration)
    num_days = _event_num_days(meeting)

    # Data gaps: critical fields missing from the meeting record — the LLM is
    # told to state its assumptions instead of silently filling with generics.
    missing_fields = [
        f for f in ("industry", "visit_focus", "meeting_objective", "sales_plays", "pillars")
        if not meeting.get(f)
    ]

    # ------------------------------------------------------------------ #
    #  Build prompt
    # ------------------------------------------------------------------ #
    prompt = _build_agenda_prompt(
        meeting=meeting,
        total_attendee_count=total_attendee_count,
        attendees=attendees,
        c_level_attendees=c_level_attendees,
        decision_makers=decision_makers,
        technical_attendees=technical_attendees,
        remote_attendees=remote_attendees,
        external_attendees=external_attendees,
        previous=previous,
        similar=similar,
        presenter_section=presenter_section,
        ebd_section=ebd_section,
        has_ebd=has_ebd,
        presenter_recommendations=presenter_recommendations,
        correction_note=correction_note,
        num_days=num_days,
        missing_fields=missing_fields,
        schedule=_schedule_summary(meeting),
    )

    logger.info("Generating structured agenda with LLM...")

    system_msg = (
        "You are an expert executive briefing agenda creator. "
        "Generate personalized agendas based on meeting context"
        + (" and the attached document (use it for presenters, KPIs, references)" if has_ebd else "")
        + ". "
        "Be flexible: use whatever useful information is available, "
        "leave optional fields empty when data is absent, "
        "and never fabricate financial figures or customer names."
    )

    # One call: pass doc as file in user message when possible (no separate extraction)
    if has_ebd_file:
        file_part = (
            {"type": "input_file", "file_url": ebd_file_url}
            if ebd_file_url
            else {"type": "input_file", "file_id": ebd_file_id}
        )
        user_content: Any = [file_part, {"type": "text", "text": prompt}]
    else:
        user_content = prompt

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_content},
    ]

    return _call_llm_with_retry(messages, previous, similar)






def _inline_json_schema_refs(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve `$ref` / `$defs` in a Pydantic-emitted JSON schema into a flat
    schema, which is what Bedrock / Claude tool-use accepts cleanly."""
    defs = schema.pop("$defs", {}) or schema.pop("definitions", {})

    def resolve(obj):
        if isinstance(obj, dict):
            if "$ref" in obj:
                ref_name = obj["$ref"].split("/")[-1]
                resolved = resolve(defs.get(ref_name, {}))
                # Merge sibling metadata (e.g. description) on top of the resolved schema
                merged = dict(resolved) if isinstance(resolved, dict) else {}
                for k, v in obj.items():
                    if k == "$ref":
                        continue
                    merged[k] = resolve(v)
                return merged
            return {k: resolve(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [resolve(x) for x in obj]
        return obj

    return resolve(schema)


def _call_llm_bedrock(
    system_msg: str,
    user_content,
    previous: List[Dict[str, Any]],
    similar: List[Dict[str, Any]],
) -> GeneratedAgenda:
    """
    Bedrock path: Claude Haiku via Converse API with tool-use for structured output.
    Static system message is wrapped with a cachePoint so repeated agenda runs
    re-use the cached prefix.
    """
    tool_name = "emit_agenda"
    agenda_schema = _inline_json_schema_refs(GeneratedAgenda.model_json_schema())
    tool_config = {
        "tools": [
            {
                "toolSpec": {
                    "name": tool_name,
                    "description": "Emit the final structured executive briefing agenda.",
                    "inputSchema": {"json": agenda_schema},
                }
            }
        ],
        "toolChoice": {"tool": {"name": tool_name}},
    }

    # user_content is either a str (pre-extracted context) or a list of parts.
    # For Bedrock, we collapse to plain text since the file-attach path is
    # OpenAI-specific (EBD is already extracted to text upstream).
    if isinstance(user_content, list):
        text_parts = [p.get("text", "") for p in user_content if isinstance(p, dict) and p.get("type") == "text"]
        user_text = "\n\n".join(text_parts)
    else:
        user_text = user_content

    messages = [{"role": "user", "content": user_text}]

    # Split system for cache: static instructions cached, everything else fresh.
    system_blocks = [
        {"text": system_msg},
        {"cachePoint": {"type": "default"}},
    ]

    for attempt in range(2):
        try:
            response = bedrock_converse(
                messages=messages,
                system=system_blocks,
                tool_config=tool_config,
                model_id=AGENDA_BEDROCK_MODEL_ID,
                max_tokens=AGENDA_MAX_OUTPUT_TOKENS,
            )
            usage = response.get("usage", {}) or {}
            logger.info(
                f"Agenda Bedrock call: tokens in={usage.get('inputTokens', 0)}, "
                f"out={usage.get('outputTokens', 0)}, "
                f"cache_read={usage.get('cacheReadInputTokens', 0)}, "
                f"cache_write={usage.get('cacheWriteInputTokens', 0)}"
            )
            # Catch truncation here rather than letting pydantic report the
            # fields that never arrived as "missing" — that error named
            # sessions and strategic_notes and said nothing about the cause.
            if response.get("stopReason") == "max_tokens":
                raise AgendaTruncated(
                    f"agenda response hit the {AGENDA_MAX_OUTPUT_TOKENS}-token output "
                    f"limit after {usage.get('outputTokens', 0)} tokens and was cut off "
                    f"mid-object"
                )
            output_msg = response.get("output", {}).get("message", {})
            for block in output_msg.get("content", []):
                tu = block.get("toolUse")
                if tu and tu.get("name") == tool_name:
                    return GeneratedAgenda.model_validate(tu.get("input") or {})
            raise RuntimeError("Bedrock response contained no toolUse block")
        except Exception as e:
            if attempt == 0:
                logger.warning(f"Bedrock agenda call failed ({e}). Retrying with shorter prompt...")
                # Shorten: strip previous meetings and similar briefings from user message
                user_text = re.sub(
                    r"## PREVIOUS MEETINGS.*?(?=## )",
                    "## PREVIOUS MEETINGS\n\nOmitted.\n\n",
                    user_text, flags=re.DOTALL,
                )
                user_text = re.sub(
                    r"## SIMILAR BRIEFINGS.*?(?=## )",
                    "## SIMILAR BRIEFINGS\n\nOmitted.\n\n",
                    user_text, flags=re.DOTALL,
                )
                # Trimming the prompt only helps when the input was the problem.
                # Against an output ceiling the second attempt regenerates the
                # same over-long agenda and dies in the same place, so ask for a
                # shorter one instead.
                if isinstance(e, AgendaTruncated):
                    user_text += (
                        "\n\n## LENGTH CORRECTION\n\n"
                        "The previous attempt ran past the output limit and was cut off. "
                        "Produce a SHORTER agenda this time: fewer sessions, and keep every "
                        "description to one sentence.\n"
                    )
                messages = [{"role": "user", "content": user_text}]
            else:
                raise

    raise RuntimeError("Bedrock agenda call failed after 2 attempts")


def _call_llm_with_retry(
    messages: list,
    previous: List[Dict[str, Any]],
    similar: List[Dict[str, Any]],
) -> GeneratedAgenda:
    """
    Call the LLM with timeout. On failure, retry once with a shorter prompt
    (drop similar briefings and previous meetings to reduce tokens).

    Dispatches to Bedrock (default) or OpenAI based on AGENDA_PROVIDER env var.
    """
    if AGENDA_PROVIDER == "bedrock":
        # Split system + user out of OpenAI-style messages for the Bedrock call.
        system_msg = ""
        user_content: Any = ""
        for m in messages:
            if m.get("role") == "system":
                system_msg = m.get("content", "") if isinstance(m.get("content"), str) else str(m.get("content", ""))
            elif m.get("role") == "user":
                user_content = m.get("content")
        return _call_llm_bedrock(system_msg, user_content, previous, similar)

    client = _get_openai_client()

    for attempt in range(2):
        try:
            response = client.beta.chat.completions.parse(
                model=LLM_MODEL,
                messages=messages,
                response_format=GeneratedAgenda,
                temperature=1,
                timeout=LLM_TIMEOUT_SECONDS,
            )
            _u = getattr(response, "usage", None)
            if _u:
                logger.info(
                    f"Agenda OpenAI call: tokens in={getattr(_u, 'prompt_tokens', 0)}, "
                    f"out={getattr(_u, 'completion_tokens', 0)}"
                )
            return response.choices[0].message.parsed
        except Exception as e:
            if attempt == 0:
                logger.warning(f"LLM call failed ({e}). Retrying with shorter prompt...")
                # Shorten: strip previous meetings and similar briefings from user message
                shortened = _strip_prompt_sections(messages)
                messages = shortened
            else:
                raise

    # Should not reach here, but just in case
    raise RuntimeError("LLM call failed after 2 attempts")






def _compute_confidence(
    meeting: Dict[str, Any],
    attendees: List[Dict[str, Any]],
    ebd_used: bool,
    presenter_recs: List[Dict[str, Any]],
    previous_meetings: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Compute a data-completeness / confidence score (0-100) for the generated agenda.

    Factors: critical fields present, attendee count, EBD available,
    presenter recommendations, previous meeting history.
    """
    score = 0
    max_score = 0
    missing: List[str] = []

    # Critical meeting fields (5 pts each, 25 total)
    for field in ("industry", "visit_focus", "meeting_objective", "sales_plays", "pillars"):
        max_score += 5
        if meeting.get(field):
            score += 5
        else:
            missing.append(field)

    # Attendees (up to 20 pts)
    max_score += 20
    n = len(attendees)
    if n >= 5:
        score += 20
    elif n >= 1:
        score += 10
    else:
        missing.append("attendees")

    # EBD document (15 pts)
    max_score += 15
    if ebd_used:
        score += 15
    else:
        missing.append("ebd_document")

    # Presenter recommendations (10 pts)
    max_score += 10
    if len(presenter_recs) >= 3:
        score += 10
    elif len(presenter_recs) >= 1:
        score += 5

    # Previous meeting history (10 pts)
    max_score += 10
    if len(previous_meetings) >= 2:
        score += 10
    elif len(previous_meetings) >= 1:
        score += 5

    pct = round(score / max_score * 100) if max_score else 0
    level = "high" if pct >= 75 else ("medium" if pct >= 50 else "low")

    return {
        "score": pct,
        "level": level,
        "missing_data": missing,
        "detail": f"{score}/{max_score} data points",
    }


def generate_agenda(
    event_id: Optional[str] = None,
    company_name: Optional[str] = None,
    schedule_headers: Optional[Dict[str, Any]] = None,
    ebd_path: Optional[str] = None,
    ebd_url: Optional[str] = None,
    pass_ebd_directly: bool = False,
    use_default_ebd: bool = False,
    fetch_ebd_from_db: bool = True,
    output_format: Literal["structured", "markdown", "both"] = "both",
    include_provenance: bool = False,
) -> Dict[str, Any]:
    """
    Main function to generate an EBC agenda.

    Data flow:
    1. Resolve event_id (UUID → numeric if needed)
    2. Fetch meeting context from OpenSearch (SQL fallback)
    3. Resolve EBD via chain: DB → direct URL → direct upload → local extract → default
    4. Get presenter recommendations (cross-validated against attendee list)
    5. Generate structured agenda via LLM (with timeout + retry)
    6. Compute confidence score and return results

    `include_provenance` attaches the evidence trail behind every presenter
    pick under a "provenance" key. Off by default and deliberately so: the
    result dict is handed to the model as a tool result, and the trail carries
    the whole candidate pool with its source rows — the same reason `by_topic`
    is stripped below. Turn it on for the debug view and the eval harness,
    where a human or an assertion reads it instead.
    """
    # Keep original UUID for OpenSearch (which stores UUIDs), resolve numeric for SQL fallback
    original_event_id = event_id
    numeric_event_id = _resolve_event_id(event_id) if event_id else None
    if original_event_id and numeric_event_id != original_event_id:
        logger.info(f"Converted event_id: {original_event_id} -> {numeric_event_id}")

    logger.info(f"Starting agenda generation - event_id: {original_event_id}, company_name: {company_name}")

    if not original_event_id and not company_name:
        return {
            "success": False,
            "error": "Please provide either an event_id or company_name",
            "agenda_structured": None,
            "agenda_markdown": None,
        }

    try:
        # Step 1: Fetch meeting context — try UUID first (OpenSearch), fall back to numeric (SQL)
        context = _fetch_meeting_context(event_id=original_event_id, company_name=company_name)
        if not context["meeting_details"] and numeric_event_id and numeric_event_id != original_event_id:
            logger.info(f"UUID lookup failed, retrying with numeric ID: {numeric_event_id}")
            context = _fetch_meeting_context(event_id=numeric_event_id, company_name=company_name)
        if not context["meeting_details"] and original_event_id and company_name:
            context = _fetch_meeting_context(event_id=None, company_name=company_name)
        if not context["meeting_details"]:
            return {
                "success": False,
                "error": f"No meeting found for {'event_id: ' + str(original_event_id) if original_event_id else 'company: ' + company_name}",
                "agenda_structured": None,
                "agenda_markdown": None,
            }

        actual_event_id = context["meeting_details"]["event_id"]
        meeting = context["meeting_details"]
        attendees = context["attendees"]
        presenter_recommendations = _get_presenter_recommendations(context, schedule_headers)
        context["presenter_recommendations"] = presenter_recommendations
        # The tenant's real topic vocabulary. Sessions are tagged from this list
        # so phase two can match a presenter to each session's actual subject;
        # a tag outside the vocabulary would match nobody.
        try:
            from tools.presenter_suggest import _available_topics, ACTIVITIES_INDEX

            # Explicit cap: the helper defaults to 40, which silently hid most
            # of the vocabulary (266 topics at last count). 150 short names is
            # ~1KB of prompt — cheap next to the rest of it.
            context["available_topics"] = _available_topics(ACTIVITIES_INDEX, limit=150)
        except Exception as exc:
            logger.warning(f"Topic vocabulary lookup failed: {exc}")
            context["available_topics"] = []

        # Step 2: Resolve EBD via chain
        ebd_result = _resolve_ebd(
            event_id=actual_event_id,
            ebd_path=ebd_path,
            ebd_url=ebd_url,
            pass_ebd_directly=pass_ebd_directly,
            use_default_ebd=use_default_ebd,
            fetch_ebd_from_db=fetch_ebd_from_db,
        )

        # Apply quality gate on extracted text
        ebd_context = None
        ebd_file_url = None
        ebd_file_id = None
        ebd_source = None
        # "no document attached" and "a document that turned out to be empty"
        # are different facts and the caller tells the user which. ebd_used
        # alone collapses them into one, and reads as the first.
        ebd_status = "none_found"

        if ebd_result:
            ebd_source = ebd_result.get("source")
            ebd_file_url = ebd_result.get("ebd_file_url")
            ebd_file_id = ebd_result.get("ebd_file_id")

            if not ebd_file_url and not ebd_file_id:
                # Text-based EBD — run quality gate
                raw = ebd_result.get("raw_text", "")
                if raw and _ebd_quality_ok(raw):
                    ebd_context = ebd_result
                    ebd_status = "used"
                else:
                    logger.warning(f"EBD from '{ebd_source}' failed quality gate — skipping")
                    ebd_source = None
                    ebd_status = "unusable"
            else:
                ebd_status = "used"

        # Step 3: Generate agenda with LLM
        agenda: GeneratedAgenda = _generate_agenda_with_llm(
            context,
            ebd_context=ebd_context,
            ebd_file_url=ebd_file_url,
            ebd_file_id=ebd_file_id,
        )

        # Times are no longer the model's to get wrong — the scheduler assigns
        # them below from the booked window, so the old validate-and-regenerate
        # repair pass has nothing left to repair. Validation still runs, after
        # scheduling, as a cheap assertion on the result.
        expected_days = _event_num_days(meeting)
        validation_issues: List[str] = []

        _enforce_session_cap(agenda)

        logger.info(f"Successfully generated agenda for {meeting.get('company_name')}")

        # Step 4: Compute confidence score
        ebd_used = bool(ebd_context and ebd_context.get("has_ebd")) or bool(ebd_file_url or ebd_file_id)
        confidence = _compute_confidence(
            meeting, attendees, ebd_used, presenter_recommendations, context["previous_meetings"],
        )

        # Build response
        result: Dict[str, Any] = {
            "success": True,
            "company": meeting.get("company_name"),
            "industry": meeting.get("industry"),
            "visit_focus": meeting.get("visit_focus"),
            "attendee_count": len(attendees),
            "previous_meetings_count": len(context["previous_meetings"]),
            "ebd_used": ebd_used,
            "ebd_source": ebd_source,
            "ebd_status": ebd_status,
            "data_source": context.get("data_source", "unknown"),
            "session_count": len(agenda.sessions),
            "presenter_recommendations": presenter_recommendations,
            "confidence": confidence,
            "validation_issues": validation_issues,
        }

        # Strict structured output forces every schema field to be emitted, so
        # the model returns the two annotation fields too — normally null, but
        # nothing stops it inventing content for them. They belong to phase
        # two alone; clear anything the model put there.
        for _sess in agenda.sessions:
            _sess.topic_presenter_suggestion = None
            _sess.presenter_before_topic_match = None
            _sess.scheduling_note = None
            _sess.backup_presenters = []
            _sess.time_slot = ""  # the scheduler owns this; discard any model guess

        # Phase two: now that sessions exist and carry topics, ask the ranking
        # who is best for each one. The pool gathered before generation could
        # only be scoped by event/customer/industry, so topic tier and depth —
        # the top two keys in the sort — were never exercised until here.
        try:
            topic_match_summary = _assign_presenters_by_topic(
                agenda.sessions, context, schedule_headers
            )
        except Exception as exc:
            logger.warning(f"Per-session presenter matching failed: {exc}")
            topic_match_summary = {"checked": 0, "matched": 0, "reassigned": 0, "error": str(exc)}

        # Phase three: put the agenda on the clock. Runs after topic matching so
        # each session already knows who it wants, and the scheduler can reshape
        # the day to keep that person rather than settling for whoever is free.
        try:
            schedule_summary = _schedule_agenda_sessions(
                agenda, context, by_topic=topic_match_summary.get("by_topic")
            )
        except Exception as exc:
            logger.warning(f"Session scheduling failed: {exc}", exc_info=True)
            schedule_summary = {"scheduled": 0, "error": str(exc)}
        result["scheduling"] = schedule_summary

        # Built here rather than later because it needs by_topic, which is
        # dropped on the next line. Never allowed to break the response: a
        # missing trail is a worse agenda, a raised exception is no agenda.
        if include_provenance:
            try:
                from tools.agenda_provenance import build_provenance

                result["provenance"] = build_provenance(
                    agenda.sessions,
                    topic_match_summary.get("by_topic"),
                    availability=schedule_summary.get("availability"),
                )
            except Exception as exc:
                logger.warning(f"Provenance build failed: {exc}", exc_info=True)
                result["provenance"] = {"error": str(exc)}

        # The raw busy spans and the address list are scheduler working state,
        # sized by how many people were checked — same context problem as
        # by_topic. Replace them with the one fact the model should actually
        # say out loud: which days were staffed without an availability check.
        _avail = schedule_summary.pop("availability", None)
        if _avail:
            from tools.agenda_provenance import unchecked_days

            unchecked = unchecked_days(_avail)
            schedule_summary["availability_checked"] = {
                "presenters_checked": len(_avail.get("checked_emails") or []),
                "presenters_with_conflicts": len(_avail.get("busy_spans_by_email") or {}),
                "days_without_availability_check": unchecked,
                "note": (
                    "Presenter availability was only checked for days listed as "
                    "covered. Do not describe a presenter on an unchecked day as "
                    "confirmed free — say the assignment is based on topic fit."
                ) if unchecked else (
                    "Every scheduled day fell inside the checked window."
                ),
            }

        # by_topic is a working artefact for the scheduler, not an answer: it is
        # the whole candidate pool and would swamp the model's context.
        topic_match_summary.pop("by_topic", None)
        result["topic_presenter_matching"] = topic_match_summary

        # Re-validate against the real window now that times are real.
        result["validation_issues"] = _validate_agenda_sessions(
            agenda, expected_days=expected_days, meeting=meeting
        )
        result["session_count"] = len(agenda.sessions)

        if output_format in ("structured", "both"):
            result["agenda_structured"] = agenda
            result["sessions"] = [session.model_dump() for session in agenda.sessions]
            result["presenters"] = [p.model_dump() for p in agenda.oracle_presenters]
            result["strategic_notes"] = agenda.strategic_notes.model_dump()

        if output_format in ("markdown", "both"):
            result["agenda_markdown"] = agenda_to_markdown(agenda)

        return result

    except Exception as e:
        logger.error(f"Error generating agenda: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "agenda_structured": None,
            "agenda_markdown": None,
        }


# For testing
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate EBC Agenda (Structured Output)")
    parser.add_argument("--company", "-c", type=str, help="Company name")
    parser.add_argument("--event", "-e", type=str, help="Event ID")
    parser.add_argument("--ebd", type=str, help="Path to EBD PowerPoint file")
    parser.add_argument("--format", "-f", choices=["structured", "markdown", "both"], 
                        default="both", help="Output format")
    parser.add_argument("--json", action="store_true", help="Output structured data as JSON")
    
    args = parser.parse_args()
    
    # Default test values if no args provided
    company = args.company or "Apple"
    event_id = args.event
    ebd_path = args.ebd
    
    print(f"🚀 Generating STRUCTURED agenda for: {company or event_id}")
    if ebd_path:
        print(f"📄 Using EBD file: {ebd_path}")
    print("=" * 80)
    
    result = generate_agenda(
        event_id=event_id,
        company_name=company if not event_id else None,
        ebd_path=ebd_path,
        output_format=args.format
    )
    
    if not result["success"]:
        print(f"❌ Error: {result.get('error')}")
        sys.exit(1)
    
    # Show metadata
    print("\n📋 METADATA:")
    metadata = {k: v for k, v in result.items() 
                if k not in ("agenda_structured", "agenda_markdown", "sessions", "presenters", "strategic_notes")}
    print(json.dumps(metadata, indent=2, default=str))
    
    # Show structured data (if requested)
    if args.json and "sessions" in result:
        print("\n" + "="*80)
        print("📊 STRUCTURED DATA (JSON):\n")
        print(json.dumps({
            "presenters": result.get("presenters", []),
            "sessions": result.get("sessions", []),
            "strategic_notes": result.get("strategic_notes", {}),
        }, indent=2, default=str))
    
    # Show markdown (if available)
    if "agenda_markdown" in result and result["agenda_markdown"]:
        print("\n" + "="*80)
        print("📝 GENERATED AGENDA (Markdown):\n")
        print(result["agenda_markdown"])
    
    # Show session summary
    if "sessions" in result:
        print("\n" + "="*80)
        print(f"📊 SESSION SUMMARY ({len(result['sessions'])} sessions):\n")
        for i, session in enumerate(result["sessions"], 1):
            print(f"  {i}. [{session['format']}] {session['time_slot']}: {session['title']}")
            print(f"     └─ Presenter: {session['presenter']}")
