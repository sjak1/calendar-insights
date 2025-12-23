"""
EBC AI Agenda Generator Tool

Generates sample agendas for Executive Briefing Center engagement requests
by fetching relevant data and using LLM to create tailored agendas.
"""
import json
from typing import Any, Dict, Optional
from sqlalchemy import create_engine, text
from openai import OpenAI
from dotenv import load_dotenv
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logging_config import get_logger

load_dotenv()

logger = get_logger(__name__)

ORACLE_CONNECTION_URI = (
    "oracle+oracledb://BIQ_EIQ_AURORA:BIQ_EIQ_AURORA"
    "@biqdb.ciqohztp4uck.us-west-2.rds.amazonaws.com:1521/?service_name=ORCL"
)

engine = create_engine(ORACLE_CONNECTION_URI)


def _fetch_meeting_context(event_id: Optional[str] = None, company_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetch all relevant meeting context data using fixed SQL queries.
    """
    context = {
        "meeting_details": None,
        "attendees": [],
        "previous_meetings": [],
        "similar_briefings": [],
    }
    
    with engine.connect() as conn:
        # Build WHERE clause
        if event_id:
            where_clause = f"EVENTID = '{event_id}'"
            company_where = f"EVENTID = '{event_id}'"
        elif company_name:
            where_clause = f"LOWER(CUSTOMERNAME) LIKE '%{company_name.lower()}%'"
            company_where = where_clause
        else:
            logger.error("Either event_id or company_name must be provided")
            return context
        
        # 1. Get meeting details
        logger.info(f"Fetching meeting details...")
        meeting_query = f"""
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
            AND ROWNUM = 1
        """
        result = conn.execute(text(meeting_query))
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
            logger.warning(f"No meeting found for criteria")
            return context
        
        # 2. Get attendees for this event
        logger.info(f"Fetching attendees...")
        attendee_query = f"""
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
            WHERE EVENTID = '{actual_event_id}'
            AND ROWNUM <= 20
        """
        result = conn.execute(text(attendee_query))
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
        
        # 3. Get previous meetings for same company
        logger.info(f"Fetching previous meetings for {actual_company}...")
        previous_query = f"""
            SELECT DISTINCT
                EVENTID,
                TO_CHAR(DATE '1970-01-01' + (STARTDATEMS/1000)/86400, 'YYYY-MM-DD') as meeting_date,
                VISITFOCUS,
                SALESPLAY,
                PILLARS,
                MEETINGOBJECTIVE
            FROM VW_OPERATIONS_REPORT 
            WHERE CUSTOMERNAME = '{actual_company}'
            AND EVENTID != '{actual_event_id}'
            ORDER BY meeting_date DESC
            FETCH FIRST 5 ROWS ONLY
        """
        result = conn.execute(text(previous_query))
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
        
        # 4. Get similar briefings (same industry + similar visit focus)
        industry = context["meeting_details"]["industry"]
        visit_focus = context["meeting_details"]["visit_focus"]
        
        if industry:
            logger.info(f"Fetching similar briefings in {industry} industry...")
            similar_query = f"""
                SELECT DISTINCT
                    CUSTOMERNAME,
                    CUSTOMERINDUSTRY,
                    VISITFOCUS,
                    SALESPLAY,
                    PILLARS
                FROM VW_OPERATIONS_REPORT 
                WHERE CUSTOMERINDUSTRY = '{industry}'
                AND CUSTOMERNAME != '{actual_company}'
                AND ROWNUM <= 5
            """
            result = conn.execute(text(similar_query))
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


def _generate_agenda_with_llm(context: Dict[str, Any]) -> str:
    """
    Use LLM to generate a tailored agenda based on the context.
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
    
    # Build prompt
    prompt = f"""You are an Executive Briefing Center (EBC) agenda specialist. Generate a professional, tailored sample agenda based on the following engagement request data.

## MEETING CONTEXT

**Company:** {meeting.get('company_name')}
**Industry:** {meeting.get('industry')}
**Account Type:** {meeting.get('account_type')}
**Line of Business:** {meeting.get('line_of_business')}
**Visit Focus:** {meeting.get('visit_focus')}
**Meeting Objective:** {meeting.get('meeting_objective')}
**Sales Plays:** {meeting.get('sales_plays')}
**Strategic Pillars:** {meeting.get('pillars')}
**Region:** {meeting.get('region')}
**Tier:** {meeting.get('tier')}

## ATTENDEE MIX

Total Attendees: {len(attendees)}
- C-Level Executives: {len(c_level_attendees)} ({', '.join([f"{a['name']} ({a['c_level']})" for a in c_level_attendees[:3]]) or 'None'})
- Decision Makers: {len(decision_makers)}
- Technical Attendees: {len(technical_attendees)}
- Remote Participants: {len(remote_attendees)}
- External (Customer): {len(external_attendees)}

## PREVIOUS MEETINGS WITH THIS COMPANY

{json.dumps(previous, indent=2) if previous else 'No previous meetings found'}

## SIMILAR BRIEFINGS (Same Industry)

{json.dumps(similar, indent=2) if similar else 'No similar briefings found'}

## INSTRUCTIONS

Generate a professional EBC agenda that:
1. Is tailored to the company's industry ({meeting.get('industry')})
2. Incorporates the sales plays: {meeting.get('sales_plays')}
3. Aligns with strategic pillars: {meeting.get('pillars')}
4. Is appropriate for the attendee mix (especially C-level: {[a['c_level'] for a in c_level_attendees]})
5. Addresses the visit focus: {meeting.get('visit_focus')}
6. Builds on previous meetings if applicable
7. Uses a hybrid format if there are remote attendees ({len(remote_attendees)} remote)

Format the agenda with:
- Clear time slots (e.g., 09:00 AM - 10:00 AM)
- Session titles and descriptions
- Presenter placeholders
- Breaks and meals
- Notes on why each session is included
- A brief summary at the top

Keep it professional and ready for EBC Manager review."""

    logger.info("Generating agenda with LLM...")
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are an expert EBC agenda creator. Create professional, tailored executive briefing agendas."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=3000,
    )
    
    return response.choices[0].message.content


def generate_agenda(event_id: Optional[str] = None, company_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Main function to generate an EBC agenda.
    
    Args:
        event_id: Event ID to generate agenda for (optional)
        company_name: Company name to find and generate agenda for (optional)
    
    Returns:
        Dict with agenda content and metadata
    """
    logger.info(f"Starting agenda generation - event_id: {event_id}, company_name: {company_name}")
    
    if not event_id and not company_name:
        return {
            "success": False,
            "error": "Please provide either an event_id or company_name",
            "agenda": None
        }
    
    try:
        # Step 1: Fetch all context data
        context = _fetch_meeting_context(event_id=event_id, company_name=company_name)
        
        if not context["meeting_details"]:
            return {
                "success": False,
                "error": f"No meeting found for {'event_id: ' + event_id if event_id else 'company: ' + company_name}",
                "agenda": None
            }
        
        # Step 2: Generate agenda with LLM
        agenda = _generate_agenda_with_llm(context)
        
        logger.info(f"Successfully generated agenda for {context['meeting_details']['company_name']}")
        
        return {
            "success": True,
            "company": context["meeting_details"]["company_name"],
            "industry": context["meeting_details"]["industry"],
            "visit_focus": context["meeting_details"]["visit_focus"],
            "attendee_count": len(context["attendees"]),
            "previous_meetings_count": len(context["previous_meetings"]),
            "agenda": agenda
        }
        
    except Exception as e:
        logger.error(f"Error generating agenda: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "agenda": None
        }


# For testing
if __name__ == "__main__":
    # Test with a company name
    result = generate_agenda(company_name="HP")
    print(json.dumps({k: v for k, v in result.items() if k != "agenda"}, indent=2))
    print("\n" + "="*80 + "\n")
    print(result.get("agenda", "No agenda generated"))
