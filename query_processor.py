"""
Main query processing module for AI assistant.
"""
import json
from openai import OpenAI
from dotenv import load_dotenv
import datetime

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

client = OpenAI()
logger = get_logger(__name__)

# AI instructions for the assistant
AI_INSTRUCTIONS = """
You are a Senior business analyst and scheduling expert. You are given a user query. 

CRITICAL TOOL RULES:
- If the query is about meetings, attendees, schedules, or opportunity metrics, you MUST call the `query_database` tool. Do NOT answer directly. 
- For other queries (like GDP or general info), use the appropriate tool (`get_gdp` or `schedule_meeting`) if needed. 
- Do NOT invent answers; always rely on tools when relevant.

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


def process_query(query, schedule_headers=None, session_id=None, event_id=None):
    """
    Process a user query through the AI assistant with tool calling.
    
    Args:
        query: User's query string
        schedule_headers: Optional headers for BriefingIQ API calls
        session_id: Optional session ID for conversation context
        event_id: Optional event ID from header (for context-aware operations)
    
    Returns:
        Dict with response text and optional chart data
    """
    logger.info(f"Starting process_query with query: {query[:100]}... (session_id: {session_id}, event_id: {event_id})")
    
    # Get or create session
    session_id = get_or_create_session(session_id)
    
    # Get conversation history for this session
    conversation_history = get_session_history(session_id)
    
    # Build input_list: start with conversation history, then add new query
    input_list = conversation_history.copy()
    input_list.append({"role": "user", "content": query})

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


def handle_query(query, headers, session_id=None, event_id=None):
    """Entry point for handling queries."""
    return process_query(query, headers, session_id=session_id, event_id=event_id)


if __name__ == "__main__":
    # Test queries
    db_query_15 = "Give me a complete analysis for Ford Motor: show all their events with dates, total attendees, number of decision makers, remote vs in-person count, and any associated revenue or opportunity data."
    
    logger.info("Running test query")
    result = handle_query(db_query_15, None)
    logger.info(f"Test query result: {result}")
