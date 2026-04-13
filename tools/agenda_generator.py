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
"""

import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field
from sqlalchemy import text

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import engine  # noqa: E402 — shared engine from database.py
from logging_config import get_logger  # noqa: E402
from tools.extract_ebd import extract_pptx_content, format_extracted_content  # noqa: E402
try:
    from opensearch_client import search as os_search, get_suggested_presenters  # noqa: E402
except ImportError:
    os_search = None
    get_suggested_presenters = None

# PDF extraction (optional dependency)
try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Configuration (all overridable via env vars)
# ---------------------------------------------------------------------------
LLM_MODEL: str = os.getenv("AGENDA_LLM_MODEL", "gpt-5-mini")
MAX_DOCUMENT_CHARS: int = int(os.getenv("MAX_DOCUMENT_CHARS", "30000"))
AGENDA_SESSION_MIN: int = int(os.getenv("AGENDA_SESSION_MIN", "6"))
AGENDA_SESSION_MAX: int = int(os.getenv("AGENDA_SESSION_MAX", "10"))
AGENDA_DAY_START: str = os.getenv("AGENDA_DAY_START", "10:00 AM")
AGENDA_DAY_END: str = os.getenv("AGENDA_DAY_END", "5:00 PM")
AGENDA_MAX_ATTENDEES: int = int(os.getenv("AGENDA_MAX_ATTENDEES", "20"))
LLM_TIMEOUT_SECONDS: int = int(os.getenv("AGENDA_LLM_TIMEOUT", "120"))

# EBD quality gate: skip extracted text that is too short or mostly non-alpha
EBD_MIN_WORDS: int = 100
EBD_MAX_NOISE_RATIO: float = 0.5  # if >50% of chars are non-alphanumeric, skip

# Module-level OpenAI client (reused across calls)
_openai_client: Optional[OpenAI] = None


def _get_openai_client() -> OpenAI:
    """Return a singleton OpenAI client."""
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI()
    return _openai_client


# ============================================================================
# STRUCTURED OUTPUT MODELS
# ============================================================================

class OraclePresenter(BaseModel):
    """Presenter information."""
    name: str = Field(description="Full name of the presenter")
    title: str = Field(description="Job title of the presenter")


class AgendaSession(BaseModel):
    """A single session in the agenda."""
    time_slot: str = Field(description="Time range, e.g., '10:00 AM - 10:45 AM'")
    title: str = Field(description="Action-oriented session title")
    format: Literal["Presentation", "Demo", "Roundtable", "Working Session"] = Field(
        description="Session format type"
    )
    presenter: str = Field(description="Presenter name and title")
    description: str = Field(description="What will be covered in this session")
    key_metrics: Optional[str] = Field(
        default=None, 
        description="Any $ figures or KPIs being addressed (e.g., '$50M inefficient spend')"
    )
    customer_reference: Optional[str] = Field(
        default=None,
        description="Customer success reference (e.g., 'Nike achieved 40% improvement')"
    )
    attendee_consideration: Optional[str] = Field(
        default=None,
        description="How this session addresses specific attendee concerns"
    )


class StrategicNotes(BaseModel):
    """Strategic notes and recommendations."""
    derailer_handling: Optional[str] = Field(
        default=None,
        description="How the agenda addresses account derailers"
    )
    attendee_considerations: List[str] = Field(
        default_factory=list,
        description="Attendee-specific considerations"
    )
    follow_up_actions: List[str] = Field(
        default_factory=list,
        description="Recommended follow-up actions"
    )


class GeneratedAgenda(BaseModel):
    """Complete structured agenda output."""
    # Header info
    company: str = Field(description="Company name")
    industry: str = Field(description="Company industry")
    date_time: str = Field(description="Proposed date and time range")
    location: str = Field(description="Location (physical and/or virtual)")
    
    # Presenters
    oracle_presenters: List[OraclePresenter] = Field(
        description="List of presenters for the briefing"
    )
    
    # Attendee summary
    total_attendees: int = Field(description="Total number of attendees")
    c_level_count: int = Field(description="Number of C-level executives")
    decision_maker_count: int = Field(description="Number of decision makers")
    technical_count: int = Field(description="Number of technical attendees")
    remote_count: int = Field(description="Number of remote participants")
    
    # Content
    executive_summary: str = Field(
        description="2-3 sentence strategic summary of the briefing goals"
    )
    sessions: List[AgendaSession] = Field(
        description="List of agenda sessions in chronological order"
    )
    strategic_notes: StrategicNotes = Field(
        description="Strategic notes and recommendations"
    )

# Default EBD path for testing only — set DEFAULT_EBD_PATH env var to override
DEFAULT_EBD_PATH: Optional[str] = os.getenv(
    "DEFAULT_EBD_PATH",
    str(Path(__file__).parent.parent / "documents" / "ebd" / "EBD_Apple_FILLED.pptx"),
)


# ============================================================================
# UUID TO NUMERIC ID RESOLVER
# ============================================================================

def _resolve_event_id(event_id: Optional[str]) -> Optional[str]:
    """
    Resolve event_id to numeric format.
    
    Handles both:
    - UUID format from frontend headers (e.g., 'BD496D83-0DF0-4E5A-B12F-F61E51D2ACFF')
    - Numeric format from database (e.g., '731318059084')
    
    Args:
        event_id: Event ID in either UUID or numeric format
        
    Returns:
        Numeric event ID string, or None if not found
    """
    if not event_id:
        return None
    
    # Already numeric - return as-is
    if event_id.isdigit():
        return event_id
    
    # Check if it looks like a UUID (contains dashes, 36 chars)
    if '-' in event_id and len(event_id) == 36:
        logger.info(f"Resolving UUID to numeric ID: {event_id}")
        try:
            with engine.connect() as conn:
                query = text("""
                    SELECT id FROM m_request_master 
                    WHERE UPPER(unique_id) = UPPER(:uuid)
                """)
                result = conn.execute(query, {"uuid": event_id})
                row = result.fetchone()
                if row:
                    numeric_id = str(row[0])
                    logger.info(f"Resolved UUID {event_id} → {numeric_id}")
                    return numeric_id
                else:
                    logger.warning(f"UUID not found in database: {event_id}")
                    return None
        except Exception as e:
            logger.error(f"Error resolving UUID: {e}")
            return None
    
    # Unknown format - try to use as-is
    return event_id


# ============================================================================
# EBD EXTRACTION FROM DATABASE
# ============================================================================

def _extract_pdf_text(pdf_path: str) -> str:
    """
    Extract text from a PDF file using pdfplumber.

    Handles arbitrary PDF layouts — extracts both free-form text and tables,
    and concatenates them page-by-page so the LLM gets a coherent view.
    """
    if not HAS_PDFPLUMBER:
        logger.warning("pdfplumber not installed. Run: pip install pdfplumber")
        return ""

    parts: list[str] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                page_parts: list[str] = []

                # --- free-form text ---
                page_text = page.extract_text()
                if page_text and page_text.strip():
                    page_parts.append(page_text.strip())

                # --- tables (if any) ---
                tables = page.extract_tables()
                for table in tables:
                    rows = []
                    for row in table:
                        cells = [
                            (cell or "").strip() for cell in row
                        ]
                        if any(cells):
                            rows.append(" | ".join(cells))
                    if rows:
                        page_parts.append("[Table]\n" + "\n".join(rows))

                if page_parts:
                    parts.append(
                        f"--- Page {page_num} ---\n" + "\n\n".join(page_parts)
                    )

        return "\n\n".join(parts)
    except Exception as e:
        logger.error(f"Error extracting PDF text: {e}")
        return ""


def _fetch_ebd_from_db(event_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch EBD document from database for a given event.
    
    Args:
        event_id: The event ID to fetch EBD for
        
    Returns:
        Dict with 'raw_text' and 'has_ebd' if found, None otherwise
    """
    logger.info(f"Attempting to fetch EBD from database for event: {event_id}")
    
    try:
        with engine.connect() as conn:
            # Query for EBD document blob
            query = text("""
                SELECT document, file_name, content_type, file_size
                FROM VW_EVENT_DOCUMENT_REPORT 
                WHERE eventid = :event_id 
                AND document_category = 'Executive Briefing Document'
                AND document IS NOT NULL
                FETCH FIRST 1 ROW ONLY
            """)
            result = conn.execute(query, {"event_id": event_id})
            row = result.fetchone()
            
            if not row:
                logger.info(f"No EBD found in database for event: {event_id}")
                return None
            
            blob = row[0]
            filename = row[1] or "document"
            content_type = row[2] or ""
            file_size = row[3] or 0
            
            logger.info(f"Found EBD in DB: {filename} ({content_type}, {file_size} bytes)")
            
            # Determine file type and extract text
            extracted_text = ""
            
            # Save blob to temp file
            suffix = ".pdf" if "pdf" in content_type.lower() else ".pptx"
            if filename.lower().endswith(".pptx"):
                suffix = ".pptx"
            elif filename.lower().endswith(".pdf"):
                suffix = ".pdf"
            
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(blob)
                tmp_path = tmp.name
            
            try:
                if suffix == ".pdf":
                    extracted_text = _extract_pdf_text(tmp_path)
                    logger.info(f"Extracted {len(extracted_text)} chars from PDF")
                elif suffix == ".pptx":
                    # Use existing PPTX extractor
                    extracted = extract_pptx_content(tmp_path)
                    extracted_text = format_extracted_content(extracted)
                    logger.info(f"Extracted {len(extracted_text)} chars from PPTX")
                else:
                    logger.warning(f"Unsupported file type: {suffix}")
            finally:
                # Cleanup temp file
                Path(tmp_path).unlink(missing_ok=True)
            
            if extracted_text:
                return {
                    "raw_text": _truncate_document(extracted_text),
                    "has_ebd": True,
                    "source": "database",
                    "filename": filename,
                }

            return None

    except Exception as e:
        logger.error(f"Error fetching EBD from database: {e}", exc_info=True)
        return None


def _truncate_document(doc_text: str, max_chars: Optional[int] = None) -> str:
    """
    Truncate document text to stay within token-safe limits.

    If the text exceeds *max_chars* it is trimmed and a notice is appended
    so the LLM knows content was cut.
    """
    limit = max_chars or MAX_DOCUMENT_CHARS
    if len(doc_text) <= limit:
        return doc_text

    logger.warning(
        f"Document text truncated from {len(doc_text)} to {limit} chars"
    )
    return doc_text[:limit] + "\n\n[... document truncated due to length ...]"


def _ebd_quality_ok(extracted_text: str) -> bool:
    """Return True if extracted EBD text is usable (not garbled / too short)."""
    words = extracted_text.split()
    if len(words) < EBD_MIN_WORDS:
        logger.warning(f"EBD text too short ({len(words)} words < {EBD_MIN_WORDS}). Skipping.")
        return False
    alpha_chars = sum(1 for c in extracted_text if c.isalnum() or c.isspace())
    total_chars = len(extracted_text)
    if total_chars > 0 and (1 - alpha_chars / total_chars) > EBD_MAX_NOISE_RATIO:
        logger.warning(
            f"EBD text appears garbled (noise ratio {1 - alpha_chars / total_chars:.0%}). Skipping."
        )
        return False
    return True


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
                        {"term": {"eventData.VISIT_INFO.data.customerName.keyword": company_name}},
                        {"match": {"eventData.VISIT_INFO.data.customerName": {"query": company_name, "fuzziness": "AUTO"}}},
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
    visit = _deep_get(hit, "eventData.VISIT_INFO.data") or {}
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
    }
    actual_event_id = hit.get("eventId")
    actual_company = visit.get("customerName") or company_name
    logger.info(f"Found meeting for: {actual_company} (via OpenSearch)")

    # 2. Attendees — from the same event document (nested arrays)
    logger.info("Extracting attendees from event document...")
    ext_attendees = _deep_get(hit, "eventData.EXTERNAL_ATTENDEES.data")
    int_attendees = _deep_get(hit, "eventData.INTERNAL_ATTENDEES.data")
    all_raw = []
    if isinstance(ext_attendees, list):
        all_raw.extend([(a, "External") for a in ext_attendees])
    elif isinstance(ext_attendees, dict):
        all_raw.append((ext_attendees, "External"))
    if isinstance(int_attendees, list):
        all_raw.extend([(a, "Internal") for a in int_attendees])
    elif isinstance(int_attendees, dict):
        all_raw.append((int_attendees, "Internal"))

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
                        {"term": {"eventData.VISIT_INFO.data.customerName.keyword": actual_company}},
                    ],
                    "must_not": [{"term": {"eventId.keyword": actual_event_id}}] if actual_event_id else [],
                }
            },
            "sort": [{"startTime": {"order": "desc"}}],
            "size": 5,
            "_source": [
                "eventId", "startTime",
                "eventData.VISIT_INFO.data.visitFocus",
                "eventData.VISIT_INFO.data.salesPlay",
                "eventData.VISIT_INFO.data.pillars",
                "eventData.VISIT_INFO.data.meetingObjective",
            ],
        }
        prev_resp = os_search(index="events", body=prev_body, size_cap=5)
        if prev_resp.get("success"):
            for ph in prev_resp.get("hits", []):
                ps = ph["source"]
                pv = _deep_get(ps, "eventData.VISIT_INFO.data") or {}
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
    "eventId", "eventName", "startTime",
    "eventData.VISIT_INFO.data",
    "eventData.EXTERNAL_ATTENDEES.data",
    "eventData.INTERNAL_ATTENDEES.data",
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
        should_clauses.append({"term": {"eventData.VISIT_INFO.data.customerIndustry.keyword": {"value": industry, "boost": 2}}})
    if visit_focus:
        should_clauses.append({"match": {"eventData.VISIT_INFO.data.visitFocus": {"query": visit_focus, "boost": 3}}})
    if pillars:
        if isinstance(pillars, str):
            pillar_str = pillars
        elif isinstance(pillars, list):
            pillar_str = " ".join(str(p) for p in pillars)
        else:
            pillar_str = None
        if pillar_str:
            should_clauses.append({"match": {"eventData.VISIT_INFO.data.pillars": {"query": pillar_str, "boost": 1}}})

    must_not = []
    if exclude_company:
        must_not.append({"term": {"eventData.VISIT_INFO.data.customerName.keyword": exclude_company}})

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
            "eventData.VISIT_INFO.data.customerName",
            "eventData.VISIT_INFO.data.customerIndustry",
            "eventData.VISIT_INFO.data.visitFocus",
            "eventData.VISIT_INFO.data.salesPlay",
            "eventData.VISIT_INFO.data.pillars",
        ],
    }

    logger.info(f"Fetching similar briefings from OpenSearch (industry={industry}, focus={visit_focus})...")
    resp = os_search(index="events", body=body, size_cap=5)
    results = []
    if resp.get("success"):
        seen = set()
        for h in resp.get("hits", []):
            sv = _deep_get(h["source"], "eventData.VISIT_INFO.data") or {}
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
                   PILLARS, FORMTYPE, REGION, TIER
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
    Extract context from an EBD file (PPTX or PDF).
    
    Args:
        ebd_path: Path to the EBD file (PPTX or PDF)
        
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
        # Check file extension — treat anything that isn't .pdf as PPTX
        if ebd_path.lower().endswith('.pdf'):
            extracted_text = _extract_pdf_text(ebd_path)
            if extracted_text:
                ebd_context["raw_text"] = _truncate_document(extracted_text)
                ebd_context["has_ebd"] = True
                logger.info(f"Extracted {len(extracted_text)} chars from PDF")
        else:
            extracted = extract_pptx_content(ebd_path)
            formatted_text = format_extracted_content(extracted)

            ebd_context["raw_text"] = _truncate_document(formatted_text)
            ebd_context["has_ebd"] = True
            ebd_context["slide_count"] = extracted["slide_count"]
            ebd_context["table_count"] = len(extracted.get("tables", []))

            logger.info(
                f"Extracted EBD: {extracted['slide_count']} slides, "
                f"{len(extracted.get('tables', []))} tables"
            )

    except Exception as e:
        logger.error(f"Error extracting EBD: {e}", exc_info=True)

    return ebd_context


def _merge_presenter_recommendations(
    combined: Dict[str, Dict[str, Any]],
    suggestions: List[Dict[str, Any]],
    source: str,
) -> None:
    """Merge presenter suggestions from multiple scopes into one ranked map."""
    for suggestion in suggestions:
        name = (suggestion.get("presenter_name") or "").strip()
        if not name:
            continue

        existing = combined.setdefault(
            name,
            {
                "presenter_name": name,
                "session_count": 0,
                "event_count": 0,
                "sources": [],
                "sample_topic": suggestion.get("sample_topic"),
                "sample_event_id": suggestion.get("sample_event_id"),
                "sample_event_name": suggestion.get("sample_event_name"),
                "reasons": [],
            },
        )
        existing["session_count"] += int(suggestion.get("session_count") or 0)
        existing["event_count"] = max(
            existing["event_count"],
            int(suggestion.get("event_count") or 0),
        )
        if source not in existing["sources"]:
            existing["sources"].append(source)
        reason = suggestion.get("reason")
        if reason and reason not in existing["reasons"]:
            existing["reasons"].append(reason)
        if not existing.get("sample_topic") and suggestion.get("sample_topic"):
            existing["sample_topic"] = suggestion.get("sample_topic")
        if not existing.get("sample_event_id") and suggestion.get("sample_event_id"):
            existing["sample_event_id"] = suggestion.get("sample_event_id")
        if not existing.get("sample_event_name") and suggestion.get("sample_event_name"):
            existing["sample_event_name"] = suggestion.get("sample_event_name")


def _get_presenter_recommendations(context: Dict[str, Any]) -> List[Dict[str, Any]]:
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

    combined: Dict[str, Dict[str, Any]] = {}
    scoped_calls = [
        ("same_event", {"event_id": event_id, "limit": 5}),
        ("same_company", {"customer_name": company_name, "limit": 5}),
        ("industry", {"industry": industry, "limit": 8}),
    ]

    for source, kwargs in scoped_calls:
        cleaned_kwargs = {k: v for k, v in kwargs.items() if v}
        if not cleaned_kwargs:
            continue
        try:
            result = get_suggested_presenters(**cleaned_kwargs)
            if result.get("success"):
                _merge_presenter_recommendations(
                    combined,
                    result.get("suggested_presenters", []),
                    source,
                )
        except Exception as e:
            logger.warning(f"Presenter suggestions failed for source '{source}': {e}")

    ranked = sorted(
        combined.values(),
        key=lambda item: (
            -item["session_count"],
            -item["event_count"],
            item["presenter_name"].lower(),
        ),
    )

    # Cross-validate: exclude presenters who are actually attendees at this event
    attendee_names = {
        a.get("name", "").strip().lower()
        for a in context.get("attendees", [])
        if a.get("type") == "External"
    }

    recommendations = []
    for item in ranked[:8]:
        name_lower = item["presenter_name"].strip().lower()
        if name_lower in attendee_names:
            logger.info(f"Excluding presenter rec '{item['presenter_name']}' — is an external attendee")
            continue
        source_label = ", ".join(item["sources"]) if item["sources"] else "unknown"
        reason_bits = list(item["reasons"]) or [f"{item['session_count']} matched activities"]
        recommendations.append(
            {
                "presenter_name": item["presenter_name"],
                "session_count": item["session_count"],
                "event_count": item["event_count"],
                "sources": item["sources"],
                "sample_topic": item.get("sample_topic"),
                "sample_event_id": item.get("sample_event_id"),
                "sample_event_name": item.get("sample_event_name"),
                "reason": f"Sources: {source_label}. " + " | ".join(reason_bits[:2]),
            }
        )

    return recommendations


def _generate_agenda_with_llm(
    context: Dict[str, Any],
    ebd_context: Optional[Dict[str, Any]] = None,
    ebd_file_url: Optional[str] = None,
    ebd_file_id: Optional[str] = None,
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
    client = _get_openai_client()

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
    if presenter_recommendations:
        presenter_section = f"""

## PRESENTER RECOMMENDATIONS

Use these as agenda-generation hints. These names come from matched historical
activities in the same event, same company, or same topic/industry.
Only use them when they fit the session. If a presenter title is unknown, keep
the title as TBD instead of inventing one.

{json.dumps(presenter_recommendations, indent=2)}
"""

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


def _rank_previous_meetings(
    meetings: List[Dict[str, Any]], current_meeting: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    Rank and annotate previous meetings by relevance to the current one.

    Scoring: recency + visit-focus overlap + same pillars.
    Only the top 3 most relevant are kept to save prompt space.
    """
    if not meetings:
        return []

    current_focus = (current_meeting.get("visit_focus") or "").lower()
    current_pillars = set()
    cp = current_meeting.get("pillars")
    if isinstance(cp, list):
        current_pillars = {str(p).lower() for p in cp}
    elif isinstance(cp, str):
        current_pillars = {cp.lower()}

    scored = []
    for i, m in enumerate(meetings):
        score = 0.0
        # Recency: first items are most recent (already sorted desc)
        score += max(0, 5 - i)  # 5, 4, 3, 2, 1

        # Visit focus overlap
        m_focus = (m.get("visit_focus") or "").lower()
        if m_focus and current_focus:
            # Simple word overlap ratio
            cur_words = set(current_focus.split())
            m_words = set(m_focus.split())
            if cur_words & m_words:
                overlap = len(cur_words & m_words) / max(len(cur_words | m_words), 1)
                score += overlap * 5

        # Pillar overlap
        m_pillars = set()
        mp = m.get("pillars")
        if isinstance(mp, list):
            m_pillars = {str(p).lower() for p in mp}
        elif isinstance(mp, str):
            m_pillars = {mp.lower()}
        if m_pillars & current_pillars:
            score += 2

        m_copy = dict(m)
        m_copy["_relevance_score"] = round(score, 1)
        scored.append(m_copy)

    scored.sort(key=lambda x: -x["_relevance_score"])
    # Keep top 3; annotate relevance label for the LLM
    top = scored[:3]
    for m in top:
        s = m.pop("_relevance_score")
        m["relevance"] = "high" if s >= 7 else ("medium" if s >= 4 else "low")
    return top


def _build_agenda_prompt(
    *, meeting, total_attendee_count, attendees, c_level_attendees,
    decision_makers, technical_attendees, remote_attendees, external_attendees,
    previous, similar, presenter_section, ebd_section, has_ebd,
    presenter_recommendations,
) -> str:
    """Build the user prompt for the LLM."""
    return f"""Generate a professional executive briefing agenda based on the data below.

## MEETING CONTEXT

Company: {meeting.get('company_name')}
Industry: {meeting.get('industry')}
Account Type: {meeting.get('account_type')}
Line of Business: {meeting.get('line_of_business')}
Visit Focus: {meeting.get('visit_focus')}
Meeting Objective: {meeting.get('meeting_objective')}
Sales Plays: {meeting.get('sales_plays')}
Strategic Pillars: {meeting.get('pillars')}
Region: {meeting.get('region')}
Tier: {meeting.get('tier')}

## ATTENDEE MIX

Total attendees: {total_attendee_count}{f' (showing top {len(attendees)})' if total_attendee_count > len(attendees) else ''}
C-Level: {len(c_level_attendees)} ({', '.join(f"{a['name']} ({a['c_level']})" for a in c_level_attendees[:3]) or 'None'})
Decision Makers: {len(decision_makers)}
Technical: {len(technical_attendees)}
Remote: {len(remote_attendees)}
External: {len(external_attendees)}

## PREVIOUS MEETINGS (ranked by relevance)

{json.dumps(previous, indent=2) if previous else 'None'}

## SIMILAR BRIEFINGS

{json.dumps(similar, indent=2) if similar else 'None'}
{presenter_section}
{ebd_section}

## REQUIREMENTS

1. Create {AGENDA_SESSION_MIN}-{AGENDA_SESSION_MAX} sessions covering {AGENDA_DAY_START} - {AGENDA_DAY_END}.
2. Include a lunch break.
3. Tailor to {meeting.get('industry')} industry.
4. Address visit focus: {meeting.get('visit_focus')}.
5. Incorporate sales plays: {meeting.get('sales_plays')}.
6. Use hybrid format if remote attendees ({len(remote_attendees)} remote).
7. Vary session formats (Presentation, Demo, Roundtable, Working Session).
8. {'Use presenter names from the document when available.' if has_ebd else 'Use presenter recommendations below when relevant.'}
9. {'If the document does not provide presenters, prefer the presenter recommendations when they fit the session; otherwise use TBD.' if presenter_recommendations else 'If no strong presenter match is available, use TBD.'}
10. {'Extract any dollar figures / KPIs from the document into key_metrics fields.' if has_ebd else ''}
11. {'Use any customer references found in the document.' if has_ebd else ''}
12. Prioritise high-relevance previous meetings when designing the flow; avoid repeating topics from recent meetings.

Hard-code the following attendee counts (do NOT make them up):
- total_attendees: {total_attendee_count}
- c_level_count: {len(c_level_attendees)}
- decision_maker_count: {len(decision_makers)}
- technical_count: {len(technical_attendees)}
- remote_count: {len(remote_attendees)}"""


def _call_llm_with_retry(
    messages: list,
    previous: List[Dict[str, Any]],
    similar: List[Dict[str, Any]],
) -> GeneratedAgenda:
    """
    Call the LLM with timeout. On failure, retry once with a shorter prompt
    (drop similar briefings and previous meetings to reduce tokens).
    """
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


def _strip_prompt_sections(messages: list) -> list:
    """Remove PREVIOUS MEETINGS and SIMILAR BRIEFINGS sections from the prompt for retry."""
    new_messages = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            # Remove sections between headers
            content = re.sub(
                r"## PREVIOUS MEETINGS.*?(?=## )", "## PREVIOUS MEETINGS (ranked by relevance)\n\nOmitted for brevity.\n\n",
                content, flags=re.DOTALL,
            )
            content = re.sub(
                r"## SIMILAR BRIEFINGS.*?(?=## )", "## SIMILAR BRIEFINGS\n\nOmitted for brevity.\n\n",
                content, flags=re.DOTALL,
            )
            new_messages.append({**msg, "content": content})
        else:
            # multipart content (file + text) — strip from the text part
            new_parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    t = part["text"]
                    t = re.sub(
                        r"## PREVIOUS MEETINGS.*?(?=## )", "## PREVIOUS MEETINGS\n\nOmitted.\n\n",
                        t, flags=re.DOTALL,
                    )
                    t = re.sub(
                        r"## SIMILAR BRIEFINGS.*?(?=## )", "## SIMILAR BRIEFINGS\n\nOmitted.\n\n",
                        t, flags=re.DOTALL,
                    )
                    new_parts.append({**part, "text": t})
                else:
                    new_parts.append(part)
            new_messages.append({**msg, "content": new_parts})
    return new_messages


def agenda_to_markdown(agenda: GeneratedAgenda) -> str:
    """
    Convert a structured GeneratedAgenda to formatted markdown.
    
    Args:
        agenda: The structured agenda object
        
    Returns:
        Formatted markdown string
    """
    lines = []
    
    # Header
    lines.append(f"# Executive Briefing Agenda for {agenda.company}")
    lines.append("")
    lines.append(f"**Company:** {agenda.company}  ")
    lines.append(f"**Industry:** {agenda.industry}  ")
    lines.append(f"**Date/Time:** {agenda.date_time}  ")
    lines.append(f"**Location:** {agenda.location}  ")
    lines.append("")
    
    # Presenters
    lines.append("## Presenters")
    for presenter in agenda.oracle_presenters:
        lines.append(f"- {presenter.name}, {presenter.title}")
    lines.append("")
    
    # Attendee Summary
    lines.append("## Attendee Summary")
    lines.append(f"- **Total Attendees:** {agenda.total_attendees}")
    lines.append(f"- **C-Level Executives:** {agenda.c_level_count}")
    lines.append(f"- **Decision Makers:** {agenda.decision_maker_count}")
    lines.append(f"- **Technical Attendees:** {agenda.technical_count}")
    lines.append(f"- **Remote Participants:** {agenda.remote_count}")
    lines.append("")
    
    # Executive Summary
    lines.append("## Executive Summary")
    lines.append(agenda.executive_summary)
    lines.append("")
    
    # Sessions
    lines.append("---")
    lines.append("")
    lines.append("## Agenda Sessions")
    lines.append("")
    
    for session in agenda.sessions:
        lines.append(f"### {session.time_slot}")
        lines.append(f"**Title:** {session.title}  ")
        lines.append(f"**Format:** {session.format}  ")
        lines.append(f"**Presenter:** {session.presenter}  ")
        lines.append(f"**Description:** {session.description}  ")
        if session.key_metrics:
            lines.append(f"**Key Metrics:** {session.key_metrics}  ")
        if session.customer_reference:
            lines.append(f"**Customer Reference:** {session.customer_reference}  ")
        if session.attendee_consideration:
            lines.append(f"**Attendee Consideration:** {session.attendee_consideration}")
        lines.append("")
    
    # Strategic Notes
    lines.append("---")
    lines.append("")
    lines.append("## Strategic Notes")
    lines.append("")
    
    if agenda.strategic_notes.derailer_handling:
        lines.append(f"**Derailer Handling:** {agenda.strategic_notes.derailer_handling}")
        lines.append("")
    
    if agenda.strategic_notes.attendee_considerations:
        lines.append("**Attendee Considerations:**")
        for consideration in agenda.strategic_notes.attendee_considerations:
            lines.append(f"- {consideration}")
        lines.append("")
    
    if agenda.strategic_notes.follow_up_actions:
        lines.append("**Recommended Follow-up Actions:**")
        for action in agenda.strategic_notes.follow_up_actions:
            lines.append(f"- {action}")
        lines.append("")
    
    return "\n".join(lines)


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
    ebd_path: Optional[str] = None,
    ebd_url: Optional[str] = None,
    pass_ebd_directly: bool = False,
    use_default_ebd: bool = False,
    fetch_ebd_from_db: bool = True,
    output_format: Literal["structured", "markdown", "both"] = "both"
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
        presenter_recommendations = _get_presenter_recommendations(context)
        context["presenter_recommendations"] = presenter_recommendations

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

        if ebd_result:
            ebd_source = ebd_result.get("source")
            ebd_file_url = ebd_result.get("ebd_file_url")
            ebd_file_id = ebd_result.get("ebd_file_id")

            if not ebd_file_url and not ebd_file_id:
                # Text-based EBD — run quality gate
                raw = ebd_result.get("raw_text", "")
                if raw and _ebd_quality_ok(raw):
                    ebd_context = ebd_result
                else:
                    logger.warning(f"EBD from '{ebd_source}' failed quality gate — skipping")
                    ebd_source = None

        # Step 3: Generate agenda with LLM
        agenda: GeneratedAgenda = _generate_agenda_with_llm(
            context,
            ebd_context=ebd_context,
            ebd_file_url=ebd_file_url,
            ebd_file_id=ebd_file_id,
        )

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
            "data_source": context.get("data_source", "unknown"),
            "session_count": len(agenda.sessions),
            "presenter_recommendations": presenter_recommendations,
            "confidence": confidence,
        }

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
