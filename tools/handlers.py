"""
Tool execution handlers for function calls.
"""
import json
from logging_config import get_logger
from scripts.sqlite_qa import ask_sqlite
from tools import (
    get_gdp,
    schedule_meeting,
    get_calendars,
    get_resources,
    get_report_data,
    format_chart,
    generate_agenda,
)
from utils.json_utils import json_dumps_safe

logger = get_logger(__name__)


def execute_tool(tool_name, args, schedule_headers=None):
    """
    Execute a tool function and return the output.
    
    Args:
        tool_name: Name of the tool to execute
        args: Arguments for the tool
        schedule_headers: Optional headers for BriefingIQ API calls
    
    Returns:
        Dict with tool output or error
    """
    try:
        if tool_name == "get_gdp":
            result = get_gdp(args["country"], args["year"])
            output = {"gdp": result}
            logger.info(f"✓ {tool_name} returned: {json.dumps(output, indent=2)}")
            return output

        elif tool_name == "schedule_meeting":
            result = schedule_meeting(
                args["calendarFromDateIso"],
                args["calendarStartTimeIso"],
                args["calendarEndTimeIso"],
                args["calendarToDateIso"],
                args.get("calendarType", "BLOCKED"),
                args.get("comments"),
                schedule_headers,
            )
            output = {"schedule_meeting": result}
            logger.info(f"✓ {tool_name} returned: {json.dumps(output, indent=2)}")
            return output

        elif tool_name == "get_calendars":
            result = get_calendars()
            output = {"get_calendars": result}
            output_str = json.dumps(output, indent=2)
            if len(output_str) > 500:
                logger.info(f"✓ {tool_name} returned: {output_str[:500]}... (truncated, {len(output_str)} chars total)")
            else:
                logger.info(f"✓ {tool_name} returned: {output_str}")
            return output

        elif tool_name == "get_resources":
            result = get_resources(args["resource_type_id"], schedule_headers)
            output = {"get_resources": result}
            output_str = json.dumps(output, indent=2)
            if len(output_str) > 500:
                logger.info(f"✓ {tool_name} returned: {output_str[:500]}... (truncated, {len(output_str)} chars total)")
            else:
                logger.info(f"✓ {tool_name} returned: {output_str}")
            return output

        elif tool_name == "get_report_data":
            result = get_report_data(
                args.get("fromDate"),
                args.get("toDate"),
                args.get("lookupType"),
                schedule_headers,
            )
            output = {"get_report_data": result}
            output_str = json.dumps(output, indent=2)
            if len(output_str) > 500:
                logger.info(f"✓ {tool_name} returned: {output_str[:500]}... (truncated, {len(output_str)} chars total)")
            else:
                logger.info(f"✓ {tool_name} returned: {output_str}")
            return output

        elif tool_name == "query_database":
            result = ask_sqlite(args["question"])
            output = {"query_database": result}
            output_str = json.dumps(output, indent=2, default=str)
            if len(output_str) > 1000:
                logger.info(f"✓ {tool_name} returned: {output_str[:1000]}... (truncated, {len(output_str)} chars total)")
            else:
                logger.info(f"✓ {tool_name} returned: {output_str}")
            return output

        elif tool_name == "format_chart":
            result = format_chart(
                args["chart_type"],
                args["title"],
                args["x_axis_data"],
                args["series_data"],
                args.get("y_axis_title")
            )
            output = {"format_chart": result}
            logger.info(f"✓ {tool_name} returned Highcharts config for '{args['chart_type']}' chart")
            return output, result  # Return both output and chart_data

        elif tool_name == "generate_agenda":
            result = generate_agenda(
                event_id=args.get("event_id"),
                company_name=args.get("company_name")
            )
            output = {"generate_agenda": result}
            output_str = json.dumps(output, indent=2, default=str)
            if len(output_str) > 1000:
                logger.info(f"✓ {tool_name} returned: {output_str[:1000]}... (truncated, {len(output_str)} chars total)")
            else:
                logger.info(f"✓ {tool_name} returned: {output_str}")
            return output

        else:
            logger.warning(f"Unknown tool: {tool_name}")
            return {"error": f"Unknown tool: {tool_name}"}

    except Exception as e:
        logger.error(f"✗ Error in {tool_name}: {e}", exc_info=True)
        return {"error": str(e)}


def process_function_calls(pending_calls, schedule_headers=None):
    """
    Process a list of function calls and return results.
    
    Returns:
        Tuple of (function_call_outputs, chart_data)
        chart_data is None if no format_chart was called
    """
    function_outputs = []
    chart_data = None

    for item in pending_calls:
        args = json.loads(item.arguments) if item.arguments else {}
        logger.info(f"→ Calling function: {item.name} with args: {json.dumps(args, indent=2)}")

        result = execute_tool(item.name, args, schedule_headers)

        # Handle format_chart special case (returns tuple)
        if item.name == "format_chart" and isinstance(result, tuple):
            output, chart_data = result
        else:
            output = result

        function_outputs.append({
            "type": "function_call_output",
            "call_id": item.call_id,
            "output": json_dumps_safe(output)
        })

    return function_outputs, chart_data
