"""
EBC AI Agenda Generator Tool

Generates sample agendas for Executive Briefing Center engagement requests
by fetching relevant data and using LLM to create tailored agendas.

Now supports EBD (Executive Briefing Document) from:
- Local PPTX files
- Database (VW_EVENT_DOCUMENT_REPORT) - auto-fetched by event_id

Uses OpenAI Structured Outputs for consistent, typed agenda generation.
"""
import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from sqlalchemy import create_engine, text
from openai import OpenAI
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import sys
import os

# PDF extraction (for EBD documents stored in DB)
try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False


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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logging_config import get_logger
from tools.extract_ebd import extract_pptx_content, format_extracted_content

load_dotenv()

logger = get_logger(__name__)

ORACLE_CONNECTION_URI = (
    "oracle+oracledb://BIQ_EIQ_AURORA:BIQ_EIQ_AURORA"
    "@biqdb.ciqohztp4uck.us-west-2.rds.amazonaws.com:1521/?service_name=ORCL"
)

engine = create_engine(ORACLE_CONNECTION_URI)

# Default EBD path for testing (set to None in production)
DEFAULT_EBD_PATH = str(Path(__file__).parent.parent / "documents" / "ebd" / "EBD_Apple_FILLED.pptx")


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
    """Extract text from a PDF file using pdfplumber."""
    if not HAS_PDFPLUMBER:
        logger.warning("pdfplumber not installed. Run: pip install pdfplumber")
        return ""
    
    text_parts = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        return "\n\n".join(text_parts)
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
                    "raw_text": extracted_text,
                    "has_ebd": True,
                    "source": "database",
                    "filename": filename,
                }
            
            return None
            
    except Exception as e:
        logger.error(f"Error fetching EBD from database: {e}", exc_info=True)
        return None


def _fetch_meeting_context(event_id: Optional[str] = None, company_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetch all relevant meeting context data using parameterized SQL queries.
    """
    context = {
        "meeting_details": None,
        "attendees": [],
        "previous_meetings": [],
        "similar_briefings": [],
    }
    
    with engine.connect() as conn:
        # Build parameterized WHERE clause
        if event_id:
            where_clause = "EVENTID = :event_id"
            params = {"event_id": event_id}
            order_by = "DATE '1970-01-01' + (STARTDATEMS/1000)/86400 DESC"
        elif company_name:
            # Try exact match first, then fall back to partial match
            # When multiple matches, prioritize companies with more complete data
            exact_name = company_name.lower().strip()
            where_clause = "LOWER(CUSTOMERNAME) = :exact_name OR LOWER(CUSTOMERNAME) LIKE :company_pattern"
            params = {
                "exact_name": exact_name,
                "company_pattern": f"%{exact_name}%"
            }
            # Priority: 1) Exact match, 2) Has industry, 3) Has visit_focus, 4) Most recent
            order_by = """CASE WHEN LOWER(CUSTOMERNAME) = :exact_name THEN 0 ELSE 1 END,
                CASE WHEN CUSTOMERINDUSTRY IS NOT NULL THEN 0 ELSE 1 END,
                CASE WHEN VISITFOCUS IS NOT NULL THEN 0 ELSE 1 END,
                DATE '1970-01-01' + (STARTDATEMS/1000)/86400 DESC"""
        else:
            logger.error("Either event_id or company_name must be provided")
            return context
        
        # 1. Get meeting details (prioritize exact matches, then by data completeness)
        logger.info("Fetching meeting details...")
        
        # Check for ambiguous matches when using company_name
        if company_name:
            count_query = text(f"""
                SELECT COUNT(DISTINCT CUSTOMERNAME)
                FROM VW_OPERATIONS_REPORT 
                WHERE {where_clause}
            """)
            count_result = conn.execute(count_query, params)
            match_count = count_result.fetchone()[0]
            if match_count > 1:
                logger.warning(f"⚠️  Ambiguous match: '{company_name}' matches {match_count} companies. "
                              f"Selecting best match based on data completeness.")
        
        meeting_query = text(f"""
            SELECT 
                EVENTID,
                CUSTOMERNAME,
                CUSTOMERINDUSTRY,
                ACCOUNTTYPE,
                LINEOFBUSINESS,
                VISITFOCUS,
                MEETINGOBJECTIVE,
                SALESPLAY,
                PILLARS,
                FORMTYPE,
                REGION,
                TIER
            FROM VW_OPERATIONS_REPORT 
            WHERE {where_clause}
            ORDER BY {order_by}
            FETCH FIRST 1 ROW ONLY
        """)
        result = conn.execute(meeting_query, params)
        row = result.fetchone()
        
        if row:
            context["meeting_details"] = {
                "event_id": row[0],
                "company_name": row[1],
                "industry": row[2],
                "account_type": _parse_json_field(row[3]),
                "line_of_business": row[4],
                "visit_focus": row[5],
                "meeting_objective": row[6],
                "sales_plays": _parse_json_field(row[7]),
                "pillars": _parse_json_field(row[8]),
                "form_type": row[9],
                "region": row[10],
                "tier": row[11],
            }
            actual_company = row[1]
            actual_event_id = row[0]
            logger.info(f"Found meeting for: {actual_company}")
        else:
            logger.warning("No meeting found for criteria")
            return context
        
        # 2. Get attendees for this event (parameterized)
        logger.info("Fetching attendees...")
        attendee_query = text("""
            SELECT 
                FIRSTNAME || ' ' || LASTNAME as full_name,
                BUSINESSTITLE,
                CHIEFOFFICERTITLE,
                DECISIONMAKER,
                INFLUENCER,
                ISTECHNICAL,
                ATTENDEETYPE,
                ISREMOTE
            FROM VW_ATTENDEE_REPORT 
            WHERE EVENTID = :event_id
            AND ROWNUM <= 20
        """)
        result = conn.execute(attendee_query, {"event_id": actual_event_id})
        for row in result:
            context["attendees"].append({
                "name": row[0],
                "title": row[1],
                "c_level": row[2],
                "decision_maker": row[3] == "Yes",
                "influencer": row[4] == "Yes",
                "technical": row[5] == "Yes",
                "type": row[6],
                "remote": row[7] == "Yes",
            })
        logger.info(f"Found {len(context['attendees'])} attendees")
        
        # 3. Get previous meetings for same company (parameterized)
        logger.info(f"Fetching previous meetings for {actual_company}...")
        previous_query = text("""
            SELECT DISTINCT
                EVENTID,
                TO_CHAR(DATE '1970-01-01' + (STARTDATEMS/1000)/86400, 'YYYY-MM-DD') as meeting_date,
                VISITFOCUS,
                SALESPLAY,
                PILLARS,
                MEETINGOBJECTIVE
            FROM VW_OPERATIONS_REPORT 
            WHERE CUSTOMERNAME = :company_name
            AND EVENTID != :event_id
            ORDER BY meeting_date DESC
            FETCH FIRST 5 ROWS ONLY
        """)
        result = conn.execute(previous_query, {"company_name": actual_company, "event_id": actual_event_id})
        for row in result:
            context["previous_meetings"].append({
                "event_id": row[0],
                "date": row[1],
                "visit_focus": row[2],
                "sales_plays": _parse_json_field(row[3]),
                "pillars": _parse_json_field(row[4]),
                "objective": row[5],
            })
        logger.info(f"Found {len(context['previous_meetings'])} previous meetings")
        
        # 4. Get similar briefings (same industry) - parameterized
        industry = context["meeting_details"]["industry"]
        
        if industry:
            logger.info(f"Fetching similar briefings in {industry} industry...")
            similar_query = text("""
                SELECT DISTINCT
                    CUSTOMERNAME,
                    CUSTOMERINDUSTRY,
                    VISITFOCUS,
                    SALESPLAY,
                    PILLARS
                FROM VW_OPERATIONS_REPORT 
                WHERE CUSTOMERINDUSTRY = :industry
                AND CUSTOMERNAME != :company_name
                AND ROWNUM <= 5
            """)
            result = conn.execute(similar_query, {"industry": industry, "company_name": actual_company})
            for row in result:
                context["similar_briefings"].append({
                    "company": row[0],
                    "industry": row[1],
                    "visit_focus": row[2],
                    "sales_plays": _parse_json_field(row[3]),
                    "pillars": _parse_json_field(row[4]),
                })
            logger.info(f"Found {len(context['similar_briefings'])} similar briefings")
    
    return context


def _parse_json_field(value: str) -> Any:
    """Parse a field that might be JSON array or plain string."""
    if value is None:
        return None
    if isinstance(value, str) and value.startswith("["):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
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
        # Check file extension
        if ebd_path.lower().endswith('.pdf'):
            # Extract from PDF
            extracted_text = _extract_pdf_text(ebd_path)
            if extracted_text:
                ebd_context["raw_text"] = extracted_text
                ebd_context["has_ebd"] = True
                logger.info(f"Extracted {len(extracted_text)} chars from PDF")
        else:
            # Extract from PPTX
            extracted = extract_pptx_content(ebd_path)
            formatted_text = format_extracted_content(extracted)
            
            ebd_context["raw_text"] = formatted_text
            ebd_context["has_ebd"] = True
            ebd_context["slide_count"] = extracted["slide_count"]
            ebd_context["table_count"] = len(extracted.get("tables", []))
            
            logger.info(f"Extracted EBD: {extracted['slide_count']} slides, {len(extracted.get('tables', []))} tables")
        
    except Exception as e:
        logger.error(f"Error extracting EBD: {e}", exc_info=True)
    
    return ebd_context


def _generate_agenda_with_llm(
    context: Dict[str, Any], 
    ebd_context: Optional[Dict[str, Any]] = None
) -> GeneratedAgenda:
    """
    Use LLM to generate a tailored agenda based on the context.
    
    Uses OpenAI Structured Outputs for consistent, typed responses.
    
    Args:
        context: Meeting context from database
        ebd_context: Optional EBD document context for richer data
        
    Returns:
        GeneratedAgenda: Structured agenda object
    """
    client = OpenAI()
    
    meeting = context["meeting_details"]
    attendees = context["attendees"]
    previous = context["previous_meetings"]
    similar = context["similar_briefings"]
    
    # Analyze attendee mix
    c_level_attendees = [a for a in attendees if a.get("c_level")]
    decision_makers = [a for a in attendees if a.get("decision_maker")]
    technical_attendees = [a for a in attendees if a.get("technical")]
    remote_attendees = [a for a in attendees if a.get("remote")]
    external_attendees = [a for a in attendees if a.get("type") == "External"]
    
    # Build document context section if available (document-agnostic approach)
    ebd_section = ""
    if ebd_context and ebd_context.get("has_ebd"):
        ebd_section = f"""

## ADDITIONAL DOCUMENT CONTEXT

The following content was extracted from an attached document. This document MAY contain useful information such as:
- Business challenges or pain points
- Financial figures or metrics
- Presenter/speaker names and titles
- Customer references or case studies
- Meeting objectives or talking points
- Attendee information or concerns

**NOTE**: The document format may vary - extract and use any relevant information you find. If certain information is not present, that's fine - use placeholders or skip those fields.

--- BEGIN DOCUMENT CONTENT ---
{ebd_context.get('raw_text', 'No content available')}
--- END DOCUMENT CONTENT ---

GUIDELINES FOR USING DOCUMENT CONTENT:

1. **Financial Figures**: IF any dollar amounts, percentages, or metrics are mentioned, include them in key_metrics fields.

2. **Customer References**: IF any company names or case studies are mentioned, use them in customer_reference fields.

3. **Presenter Names**: IF presenter/speaker names are mentioned, use them. Otherwise, use placeholders like 'TBD'.

4. **Attendee Concerns**: IF any attendee perspectives or concerns are mentioned, address them in attendee_consideration fields.

5. **Challenges/Objectives**: IF business challenges or meeting objectives are mentioned, incorporate them into session themes.

6. **Be Flexible**: Don't force information that isn't there. If the document doesn't contain certain data, simply omit those optional fields or use generic placeholders.
"""
    
    # Build prompt for structured output
    prompt = f"""Generate a professional executive briefing agenda based on this data:

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

Total: {len(attendees)}
C-Level: {len(c_level_attendees)} ({', '.join([f"{a['name']} ({a['c_level']})" for a in c_level_attendees[:3]]) or 'None'})
Decision Makers: {len(decision_makers)}
Technical: {len(technical_attendees)}
Remote: {len(remote_attendees)}
External: {len(external_attendees)}

## PREVIOUS MEETINGS

{json.dumps(previous, indent=2) if previous else 'None'}

## SIMILAR BRIEFINGS

{json.dumps(similar, indent=2) if similar else 'None'}
{ebd_section}

## REQUIREMENTS

1. Create 6-10 sessions covering the full day (10 AM - 5 PM typical)
2. Include lunch break
3. Tailor to {meeting.get('industry')} industry
4. Address visit focus: {meeting.get('visit_focus')}
5. Incorporate sales plays: {meeting.get('sales_plays')}
6. Use hybrid format if remote attendees ({len(remote_attendees)} remote)
7. Vary session formats (Presentation, Demo, Roundtable, Working Session)
{"8. If document contains presenter names, use them. Otherwise use placeholders like 'TBD'" if ebd_context and ebd_context.get("has_ebd") else "8. Use placeholder presenter names like 'TBD'"}
{"9. If document contains financial figures or metrics, include them in key_metrics" if ebd_context and ebd_context.get("has_ebd") else ""}
{"10. If document contains customer references, use them in customer_reference fields" if ebd_context and ebd_context.get("has_ebd") else ""}

Fill in ALL fields in the structured output. For attendee counts, use:
- total_attendees: {len(attendees)}
- c_level_count: {len(c_level_attendees)}
- decision_maker_count: {len(decision_makers)}
- technical_count: {len(technical_attendees)}
- remote_count: {len(remote_attendees)}"""

    logger.info("Generating structured agenda with LLM...")
    
    # Build system message
    if ebd_context and ebd_context.get("has_ebd"):
        system_msg = """You are an expert executive briefing agenda creator. Generate personalized agendas based on meeting context and any available document content.

GUIDELINES when document content is available:
- Extract and use any relevant information found in the document
- IF presenter names are found, use them; otherwise use placeholders
- IF financial figures are found, include them in key_metrics
- IF customer references are found, use them in customer_reference fields
- IF attendee concerns are mentioned, address them in attendee_consideration
- Don't assume the document has a specific structure - be flexible
- It's OK to leave optional fields empty if information isn't available
- Vary session formats (Presentation, Demo, Roundtable, Working Session)"""
    else:
        system_msg = "You are an expert executive briefing agenda creator. Create professional, tailored agendas that address meeting objectives and attendee needs."
    
    # Use structured output parsing
    response = client.beta.chat.completions.parse(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt}
        ],
        response_format=GeneratedAgenda,
        temperature=0.7,
    )
    
    return response.choices[0].message.parsed


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


def generate_agenda(
    event_id: Optional[str] = None, 
    company_name: Optional[str] = None,
    ebd_path: Optional[str] = None,
    use_default_ebd: bool = False,  # Only use default for explicit testing
    fetch_ebd_from_db: bool = True,  # Fetch EBD from VW_EVENT_DOCUMENT_REPORT
    output_format: Literal["structured", "markdown", "both"] = "both"
) -> Dict[str, Any]:
    """
    Main function to generate an EBC agenda.
    
    EBD source priority:
    1. Database (VW_EVENT_DOCUMENT_REPORT) - if fetch_ebd_from_db=True
    2. Local file (ebd_path)
    3. Default test file (if use_default_ebd=True)
    
    Args:
        event_id: Event ID to generate agenda for (optional)
        company_name: Company name to find and generate agenda for (optional)
        ebd_path: Path to EBD PowerPoint file for rich context (optional)
        use_default_ebd: If True and no EBD found, use DEFAULT_EBD_PATH for testing
        fetch_ebd_from_db: If True, try to fetch EBD from database first
        output_format: "structured" (Pydantic model), "markdown" (formatted text), or "both"
    
    Returns:
        Dict with:
        - success: bool
        - company, industry, visit_focus: metadata
        - agenda_structured: GeneratedAgenda object (if output_format includes structured)
        - agenda_markdown: Formatted markdown string (if output_format includes markdown)
        - sessions: List of session dicts for easy access
        - ebd_source: "database", "local_file", or None
    """
    # Resolve event_id (handles UUID → numeric conversion)
    original_event_id = event_id
    if event_id:
        event_id = _resolve_event_id(event_id)
        if original_event_id != event_id:
            logger.info(f"🔄 Converted event_id: {original_event_id} → {event_id}")
    
    logger.info(f"Starting agenda generation - event_id: {event_id}, company_name: {company_name}")
    
    if not event_id and not company_name:
        return {
            "success": False,
            "error": "Please provide either an event_id or company_name",
            "agenda_structured": None,
            "agenda_markdown": None,
        }
    
    try:
        # Step 1: Fetch all context data from database
        context = _fetch_meeting_context(event_id=event_id, company_name=company_name)
        
        if not context["meeting_details"]:
            return {
                "success": False,
                "error": f"No meeting found for {'event_id: ' + event_id if event_id else 'company: ' + company_name}",
                "agenda_structured": None,
                "agenda_markdown": None,
            }
        
        actual_event_id = context["meeting_details"]["event_id"]
        meeting = context["meeting_details"]
        attendees = context["attendees"]
        
        # Validate data quality - warn if critical fields are missing
        missing_fields = []
        if not meeting.get("industry"):
            missing_fields.append("industry")
        if not meeting.get("visit_focus"):
            missing_fields.append("visit_focus")
        if len(attendees) == 0:
            missing_fields.append("attendees")
        
        if missing_fields:
            logger.warning(f"⚠️  Missing critical data for {meeting.get('company_name')}: {', '.join(missing_fields)}. "
                          f"Generated agenda may contain placeholder/hallucinated content.")
        
        # Step 2: Try to get EBD - priority: DB > local file > default
        ebd_context = None
        ebd_source = None
        
        # 2a. Try database first
        if fetch_ebd_from_db and actual_event_id:
            ebd_context = _fetch_ebd_from_db(actual_event_id)
            if ebd_context and ebd_context.get("has_ebd"):
                ebd_source = "database"
                logger.info(f"Using EBD from database: {ebd_context.get('filename', 'unknown')}")
        
        # 2b. Try local file if DB didn't have it
        if not ebd_context and ebd_path:
            ebd_context = _extract_ebd_context(ebd_path)
            if ebd_context and ebd_context.get("has_ebd"):
                ebd_source = "local_file"
                logger.info(f"Using EBD from local file: {ebd_path}")
        
        # 2c. Try default file for testing
        if not ebd_context and use_default_ebd and DEFAULT_EBD_PATH and Path(DEFAULT_EBD_PATH).exists():
            ebd_context = _extract_ebd_context(DEFAULT_EBD_PATH)
            if ebd_context and ebd_context.get("has_ebd"):
                ebd_source = "default_test_file"
                logger.info(f"Using default EBD for testing: {DEFAULT_EBD_PATH}")
        
        if not ebd_context:
            logger.info("No EBD available - generating agenda without EBD context")
        
        # Step 3: Generate structured agenda with LLM
        agenda: GeneratedAgenda = _generate_agenda_with_llm(context, ebd_context)
        
        logger.info(f"Successfully generated agenda for {context['meeting_details']['company_name']}")
        
        # Build response
        result = {
            "success": True,
            "company": context["meeting_details"]["company_name"],
            "industry": context["meeting_details"]["industry"],
            "visit_focus": context["meeting_details"]["visit_focus"],
            "attendee_count": len(context["attendees"]),
            "previous_meetings_count": len(context["previous_meetings"]),
            "ebd_used": ebd_context.get("has_ebd", False) if ebd_context else False,
            "ebd_source": ebd_source,  # "database", "local_file", "default_test_file", or None
            "session_count": len(agenda.sessions),
        }
        
        # Add structured output
        if output_format in ("structured", "both"):
            result["agenda_structured"] = agenda
            # Also provide sessions as easy-access list of dicts
            result["sessions"] = [session.model_dump() for session in agenda.sessions]
            result["presenters"] = [p.model_dump() for p in agenda.oracle_presenters]
            result["strategic_notes"] = agenda.strategic_notes.model_dump()
        
        # Add markdown output
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
