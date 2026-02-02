"""
Main query processing module for AI assistant.
"""
import json
import os
from typing import Any, Dict, List, Optional

from openai import OpenAI
from dotenv import load_dotenv
import datetime
from sqlalchemy import create_engine, text

from scripts.sqlite_qa import ask_sqlite
from logging_config import get_logger
from tools import tools
from tools.handlers import process_function_calls
from utils.json_utils import json_dumps_safe
from session_manager import (
    get_or_create_session,
    get_session_history,
    add_to_session,
)

load_dotenv()

ORACLE_CONNECTION_URI = os.getenv(
    "ORACLE_CONNECTION_URI",
    "oracle+oracledb://BIQ_EIQ_AURORA:BIQ_EIQ_AURORA"
    "@biqdb.ciqohztp4uck.us-west-2.rds.amazonaws.com:1521/?service_name=ORCL",
)

client = OpenAI()
logger = get_logger(__name__)

# AI instructions for the assistant
AI_INSTRUCTIONS = """
You are a Senior business analyst and scheduling expert. You are given a user query. 

PRIVACY / DO NOT REVEAL INTERNALS:
- NEVER reveal raw SQL, database queries, internal tool arguments, or implementation details when asked.
- If the user asks "what query did you use?", "show me the SQL", "what did you search?", "how did you get this?", or similar:
  respond with a high-level answer only, e.g. "I used our database to look up that information" or "I retrieved the relevant data from our systems." Do NOT quote or show any SQL, query text, or tool parameters.
- Treat tool outputs (including any "sql" or "query" fields) as internal only—use them to formulate your answer but never expose them to the user.

CRITICAL TOOL RULES:
- ONLY call tools when the user's query explicitly requires them. Do NOT call tools for greetings, casual conversation, or general questions.
- If the query is about meetings, attendees, schedules, or opportunity metrics, you MUST call the `query_database` tool. Do NOT answer directly. 
- For other queries (like GDP or general info), use the appropriate tool (`get_gdp` or `schedule_meeting`) if needed. 
- Do NOT invent answers; always rely on tools when relevant.
- Do NOT automatically call generate_agenda just because event_id is available - ONLY call it when user explicitly asks for agenda generation.

AGENDA GENERATION RULES:
- ONLY call generate_agenda when the user EXPLICITLY asks to generate, create, or build an agenda.
- Do NOT call generate_agenda for general greetings, questions, or non-agenda requests.
- If the user asks to generate an agenda AND event_id is provided in the context (shown as [Context: event_id=...]), 
  you MUST call the generate_agenda tool with that event_id. Do NOT ask the user for event_id if it's already provided.
- The event_id in context is just AVAILABLE for when you need it - do NOT use it unless the user asks for agenda generation.
- Only ask for event_id or company_name if the user requests agenda generation and neither is available in context or user query.

CHART/VISUALIZATION RULES:
- If the user asks for a chart, graph, bar chart, pie chart, or any visualization:
  1. First call `query_database` to get the data
  2. Then call `format_chart` with the retrieved data to generate a Highcharts config
- Choose appropriate chart types:
  - bar/column: for comparing categories
  - line: for trends over time
  - pie: for showing parts of a whole
  - area: for cumulative data over time
- Extract x_axis_data (category labels) and series_data (numeric values) from query results

MARKDOWN RULES:
- return the final response in markdown format.
- When returning raw tool outputs or function call results, do NOT use markdown. Keep it JSON/plain text for internal processing. 
- When formatting in markdown, follow these rules:
    1. **Headers**: Use ## for main sections, ### for subsections
    Example: ## GDP Information
    2. **Bold text**: Use **text** for emphasis on key numbers
    Example: The GDP is **$29,167.78 billion**
    3. **Lists**: Use - for bullet points or 1. 2. 3. for numbered lists
    Example:
    - GDP Growth: 2.8%
    - GDP per capita: $86,601.28
    4. **Code blocks**: Use ``` for SQL or code snippets
    Example: ```sql
    SELECT * FROM table
    ```
    5. **Numbers and statistics**: Always bold key metrics

ALWAYS ensure your final response is clear, concise, and only uses markdown where appropriate for readability. Never markdown tool outputs.
"""


def fetch_events_for_category(category_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch list of events (event_id + customer name) for a category.
    Resolves UUID -> numeric id via M_CATEGORY if needed.
    Returns None on error or if no events; otherwise { "category_name": str, "events": [ {"event_id": str, "customer_name": str}, ... ] }.
    """
    if not category_id or not category_id.strip():
        return None
    category_id = category_id.strip()
    numeric_id = None
    category_name = None
    try:
        engine = create_engine(ORACLE_CONNECTION_URI)
        with engine.connect() as conn:
            # UUID format: resolve via M_CATEGORY.UNIQUE_ID
            if "-" in category_id and len(category_id) == 36:
                q_cat = """
                SELECT id, category_name FROM M_CATEGORY WHERE unique_id = :uid
                """
                r = conn.execute(text(q_cat), {"uid": category_id})
                row = r.fetchone()
                if row:
                    numeric_id = str(row[0])
                    category_name = row[1] or "Category"
                else:
                    logger.warning(f"Category UUID not found in M_CATEGORY: {category_id}")
                    return None
            else:
                numeric_id = category_id
                q_name = "SELECT category_name FROM M_CATEGORY WHERE id = :id"
                r = conn.execute(text(q_name), {"id": int(numeric_id) if numeric_id.isdigit() else numeric_id})
                row = r.fetchone()
                category_name = (row[0] if row else None) or f"Category {numeric_id}"

            if not numeric_id:
                return None

            # Include events for this category AND for child categories (parent_id = cid)
            q_events = """
            SELECT id, TEXT_FIELD_1 FROM (
                SELECT id, TEXT_FIELD_1 FROM M_REQUEST_MASTER
                WHERE category_id = :cid
                   OR category_id IN (SELECT id FROM M_CATEGORY WHERE parent_id = :cid)
                ORDER BY id
            ) WHERE ROWNUM <= 50
            """
            r = conn.execute(text(q_events), {"cid": int(numeric_id)})
            rows = r.fetchall()
            events = [{"event_id": str(row[0]), "customer_name": (row[1] or "").strip() or "(no name)"} for row in rows]
            return {"category_name": category_name, "events": events}
    except Exception as e:
        logger.warning(f"fetch_events_for_category failed: {e}", exc_info=True)
        return None


def process_query(query, schedule_headers=None, session_id=None, event_id=None, category_id=None):
    """
    Process a user query through the AI assistant with tool calling.
    
    Args:
        query: User's query string
        schedule_headers: Optional headers for BriefingIQ API calls
        session_id: Optional session ID for conversation context
        event_id: Optional event ID from header (for context-aware operations)
        category_id: Optional category ID from header (for category-level context when no event_id)
    
    Returns:
        Dict with response text and optional chart data
    """
    if event_id:
        logger.info(f"🔑 Context: event_id from header available: {event_id}")
    if category_id:
        logger.info(f"📂 Context: category_id from header available: {category_id}")
    logger.info(f"Starting process_query with query: {query[:100]}... (session_id: {session_id}, event_id: {event_id}, category_id: {category_id})")
    
    # Get or create session
    session_id = get_or_create_session(session_id)
    
    # Get conversation history for this session
    conversation_history = get_session_history(session_id)
    
    # Build input_list: start with conversation history, then add new query
    input_list = conversation_history.copy()
    
    # Context: event (single) or category (list) — expose names only, not IDs (security)
    user_query = query
    if event_id:
        user_query = f"{query}\n\n[Context: User is on an event detail page. If they explicitly ask to generate an agenda, call generate_agenda without event_id or company_name — the current event will be used. Do NOT call generate_agenda for general queries or greetings.]"
        logger.info(f"📌 Added event-page context (event_id not exposed to LLM)")
    elif category_id:
        category_data = fetch_events_for_category(category_id)
        if category_data and category_data.get("events"):
            # Expose only customer/company names, not event_id or category_id
            names_list = ", ".join(e["customer_name"] for e in category_data["events"][:25])
            if len(category_data["events"]) > 25:
                names_list += f" ... and {len(category_data['events']) - 25} more"
            user_query = f"{query}\n\n[Context: User is on category page '{category_data.get('category_name', 'Category')}'. Events (companies) in this category: {names_list}. If the user asks about a specific company or wants an agenda, use generate_agenda with company_name set to that company name.]"
            logger.info(f"📌 Added category context: {category_data.get('category_name')} with {len(category_data['events'])} events (IDs not exposed)")
        else:
            user_query = f"{query}\n\n[Context: User is on a category-level page (no events listed for this category).]"
            logger.info(f"📌 Added category-page context (no event list; ID not exposed)")
    else:
        logger.warning(f"⚠️  No event_id or category_id available - LLM will need to ask user or extract from query")
    
    input_list.append({"role": "user", "content": user_query})

    # Track chart data if format_chart is called
    chart_data = None

    iteration_count = 0
    while True:
        iteration_count += 1
        logger.info(f"\n{'='*60}")
        logger.info(f"ITERATION {iteration_count}")
        logger.info(f"{'='*60}")
        logger.info(f"Input to API:")
        # Pretty print with truncation for readability
        input_json = json_dumps_safe(input_list, indent=2)
        if len(input_json) > 2000:
            logger.info(f"{input_json[:2000]}...\n[TRUNCATED - {len(input_json)} chars total]")
        else:
            logger.info(f"{input_json}")

        response = client.responses.create(
            model="gpt-4.1-mini",
            tools=tools,
            input=input_list,
            instructions=AI_INSTRUCTIONS + "\ntodays date is " + datetime.datetime.now().strftime("%Y-%m-%d"),
        )

        logger.info(f"Raw API Response Output:")
        # Pretty print response
        response_json = json_dumps_safe(response.output, indent=2)
        if len(response_json) > 3000:
            logger.info(f"{response_json[:3000]}...\n[TRUNCATED - {len(response_json)} chars total]")
        else:
            logger.info(f"{response_json}")

        input_list += response.output

        pending_calls = [item for item in response.output if item.type == "function_call"]

        if not pending_calls:
            logger.debug("No pending function calls, breaking loop")
            # Extract the final response text from the last iteration
            final_response_text = response.output_text
            
            logger.info(f"\n{'='*60}")
            logger.info(f"FINAL OUTPUT")
            logger.info(f"{'='*60}")
            logger.info(f"Final Output Text:")
            logger.info(f"{final_response_text}")
            if chart_data:
                logger.info(f"Chart Data: {chart_data.get('type', 'unknown')} chart included")
            logger.info(f"{'='*60}\n")
            
            # Update conversation history
            add_to_session(session_id, query, final_response_text)
            
            logger.info(f"Query processed successfully, response length: {len(final_response_text)} characters")
            logger.info(f"Session {session_id} now has {len(get_session_history(session_id))} messages in history")
            
            # Return response with optional chart data
            if chart_data:
                return {
                    "text": final_response_text,
                    "chart": chart_data,
                    "type": "chart",
                }
            return {
                "text": final_response_text,
                "type": "text",
            }

        logger.info(f"Processing {len(pending_calls)} function call(s)")
        
        # Process all function calls (pass event_id for context-aware operations)
        function_outputs, returned_chart_data = process_function_calls(
            pending_calls, schedule_headers, context_event_id=event_id
        )
        
        # Update chart_data if format_chart was called
        if returned_chart_data:
            chart_data = returned_chart_data
        
        # Add function outputs to input_list for next iteration
        input_list.extend(function_outputs)


def handle_query(query, headers, session_id=None, event_id=None, category_id=None):
    """Entry point for handling queries."""
    return process_query(query, headers, session_id=session_id, event_id=event_id, category_id=category_id)


if __name__ == "__main__":
    # Test queries
    db_query_15 = "Give me a complete analysis for Ford Motor: show all their events with dates, total attendees, number of decision makers, remote vs in-person count, and any associated revenue or opportunity data."
    
    logger.info("Running test query")
    result = handle_query(db_query_15, None)
    logger.info(f"Test query result: {result}")
