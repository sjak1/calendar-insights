"""
Main query processing module for AI assistant.
Uses AWS Bedrock Converse API (with optional OpenAI fallback).
"""

import base64
import json
import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv
import datetime
import time
from sqlalchemy import text

from logging_config import get_logger
from schema_reference import SCHEMA_REFERENCE
from tools import tools
from tools.handlers import process_function_calls
from utils.json_utils import json_dumps_safe
from session_manager import (
    get_or_create_session,
    get_session_history,
    add_to_session,
)
from database import engine
from bedrock_llm import (
    openai_tools_to_bedrock,
    converse as bedrock_converse,
    BEDROCK_MODEL_ID,
)

load_dotenv()

# Use Bedrock by default; set USE_OPENAI=1 to fall back to OpenAI
USE_BEDROCK = os.getenv("USE_BEDROCK", "1").lower() in ("1", "true", "yes")

# Claude Sonnet 4.6 on Bedrock pricing (used to estimate per-query cost in responses)
# If AWS pricing changes, update these constants.
COST_INPUT_PER_1M = 3.0  # USD per 1M input tokens
COST_OUTPUT_PER_1M = 15.0  # USD per 1M output tokens

if not USE_BEDROCK:
    from openai import OpenAI

    client = OpenAI()
else:
    client = None

logger = get_logger(__name__)


class _ToolCall:
    """Adapter for Bedrock toolUse to match handler expectations (name, arguments, call_id)."""

    def __init__(self, name: str, arguments: str, call_id: str):
        self.name = name
        self.arguments = arguments
        self.call_id = call_id


# AI instructions — minimal; tool-specific rules in tool descriptions
AI_INSTRUCTIONS = (
    """
You are a Senior business analyst and scheduling expert.

PRIVACY: Never reveal SQL, queries, tool args, or internals. Say "I retrieved the data from our systems" if asked.

PERSONA: Use user name from [Context] naturally. First greeting: "Hi [FirstName], how can I help today?" Then use name sparingly.

TOOLS: Only call when the query requires them. Greetings → no tools. Table/report/grid → generate_report. Chart → search_opensearch then format_chart. How many → count_opensearch. Search/lists → search_opensearch. Agenda → generate_agenda only when explicitly asked. Presenters → suggest_presenters. PDF/export as PDF/download PDF → generate_pdf (pass full formatted content and title). If event_id in context and user asks for agenda, use it.

SCHEMA (OpenSearch field reference):
"""
    + SCHEMA_REFERENCE
    + """

OUTPUT: Markdown for final response. No markdown for tool outputs (keep JSON/plain).
Markdown: ## for main sections, ### for subsections. **bold** for key numbers. Use - for bullets or 1. 2. 3. for numbered lists. Code: ``` blocks. Always bold key metrics.
"""
)


def process_query(
    query,
    schedule_headers=None,
    session_id=None,
    event_id=None,
    category_id=None,
    user_info=None,
):
    """
    Process a user query through the AI assistant with tool calling.

    Args:
        query: User's query string
        schedule_headers: Optional headers for BriefingIQ API calls
        session_id: Optional session ID for conversation context
        event_id: Optional event ID from header (for context-aware operations)
        category_id: Optional category ID from header (for category-level context when no event_id)
        user_info: Optional dict with user context (email, timezone, etc.)

    Returns:
        Dict with response text and optional chart data
    """
    if event_id:
        logger.info(f"🔑 Context: event_id from header available: {event_id}")
    if category_id:
        logger.info(f"📂 Context: category_id from header available: {category_id}")
    logger.info(
        f"Starting process_query with query: {query[:100]}... (session_id: {session_id}, event_id: {event_id}, category_id: {category_id})"
    )

    # Get or create session
    session_id = get_or_create_session(session_id)

    # Get conversation history for this session
    conversation_history = get_session_history(session_id)

    # Build input_list: last 6 turns (12 messages) to keep context small and fast
    input_list = conversation_history.copy()
    if len(input_list) > 12:
        input_list = input_list[-12:]

    # Build [User] line for all paths (persona)
    _user_line = ""
    if user_info:
        name = user_info.get("display_name") or user_info.get("email", "")
        tz = (
            user_info.get("requested_timezone")
            or user_info.get("context_timezone")
            or user_info.get("client_timezone", "")
        )
        parts = []
        if name:
            parts.append(f"User name: {name}")
        if tz:
            parts.append(f"Timezone: {tz}")
        _user_line = " | ".join(parts) if parts else ""

    # Structured page context: [Page] / [Scope] / [Data] / [Agenda] (+ [User])
    user_query = query
    if event_id:
        _ctx = (
            "[Page] Event detail (single event in focus)\n"
            "[Scope] Current event is used for agenda when user asks; do not expose event_id.\n"
            "[Data] Use search_opensearch as usual.\n"
            '[Agenda] Only if user asks to "generate agenda" / "create agenda" → call generate_agenda with no args. Do not call for greetings or general queries.'
        )
        user_query = f"{query}\n\n{_ctx}" + (
            f"\n[User] {_user_line}" if _user_line else ""
        )
        logger.info("📌 Added event-page context (event_id not exposed to LLM)")
    elif category_id:
        category_name = "Briefings"
        try:
            with engine.connect() as conn:
                if "-" in category_id and len(category_id) == 36:
                    result = conn.execute(
                        text(
                            "SELECT category_name FROM M_CATEGORY WHERE UPPER(unique_id) = UPPER(:uid)"
                        ),
                        {"uid": category_id},
                    )
                else:
                    result = conn.execute(
                        text("SELECT category_name FROM M_CATEGORY WHERE id = :id"),
                        {"id": int(category_id)},
                    )
                row = result.fetchone()
                if row:
                    category_name = row[0]
        except Exception as e:
            logger.warning(f"Could not fetch category name: {e}")

        _ctx = (
            f"[Page] Category — {category_name}\n"
            f'[Scope] When the query is about "these events" or this location, filter by location.data.locationName.keyword = "{category_name}".\n'
            "[Data] Use search_opensearch; apply filter when relevant.\n"
            "[Agenda] If user names a company in this category, use generate_agenda(company_name=...)."
        )
        user_query = f"{query}\n\n{_ctx}" + (
            f"\n[User] {_user_line}" if _user_line else ""
        )
        logger.info(f"📌 Added category context: {category_name}")
    else:
        if _user_line:
            user_query = f"{query}\n\n[User] {_user_line}"
        logger.warning(
            "⚠️  No event_id or category_id available - LLM will need to ask user or extract from query"
        )

    input_list.append({"role": "user", "content": user_query})

    # Track chart/report/pdf payloads when format_chart, generate_report, or generate_pdf is called
    chart_data = None
    report_data = None
    pdf_data = None

    iteration_count = 0
    total_tokens_in = 0
    total_tokens_out = 0
    query_start = time.time()

    MAX_ITERATIONS = 15
    while True:
        if iteration_count >= MAX_ITERATIONS:
            logger.error(f"🛑 Hit max iterations ({MAX_ITERATIONS}), breaking tool loop")
            return {
                "text": "I'm sorry, I wasn't able to complete the analysis within the allowed number of steps. Please try a simpler query.",
                "type": "text",
            }
        iteration_count += 1
        iter_start = time.time()
        logger.info(f"\n{'=' * 60}")
        logger.info(f"ITERATION {iteration_count}")
        logger.info(f"{'=' * 60}")
        # Context breakdown
        msg_counts = {
            "user": 0,
            "assistant": 0,
            "function_call": 0,
            "function_call_output": 0,
            "reasoning": 0,
            "other": 0,
        }
        msg_sizes = {
            "user": 0,
            "assistant": 0,
            "function_call": 0,
            "function_call_output": 0,
            "reasoning": 0,
            "other": 0,
        }
        for item in input_list:
            role = (
                item.get("role")
                if isinstance(item, dict)
                else getattr(item, "type", getattr(item, "role", "other"))
            )
            if role in msg_counts:
                key = role
            else:
                key = "other"
            msg_counts[key] += 1
            item_json = json_dumps_safe(item, indent=None)
            msg_sizes[key] += len(item_json)
        total_ctx_size = sum(msg_sizes.values())
        logger.info(f"{'─' * 50}")
        logger.info(
            f"📦 Context: {len(input_list)} messages | {total_ctx_size:,} chars"
        )
        for k in msg_counts:
            if msg_counts[k] > 0:
                logger.info(f"   {k}: {msg_counts[k]} msg(s), {msg_sizes[k]:,} chars")
        logger.info(f"{'─' * 50}")

        logger.info(f"Input to API:")
        input_json = json_dumps_safe(input_list, indent=2)
        if len(input_json) > 2000:
            logger.info(
                f"{input_json[:2000]}...\n[TRUNCATED - {len(input_json)} chars total]"
            )
        else:
            logger.info(f"{input_json}")

        llm_start = time.time()
        if USE_BEDROCK:
            system = (
                AI_INSTRUCTIONS
                + "\ntodays date is "
                + datetime.datetime.now().strftime("%Y-%m-%d")
            )
            tool_config = {
                "tools": openai_tools_to_bedrock(tools),
                "toolChoice": {"auto": {}},
            }
            response = bedrock_converse(
                messages=input_list,
                system=system,
                tool_config=tool_config,
            )
            llm_elapsed = time.time() - llm_start
            usage = response.get("usage", {})
            iter_in = usage.get("inputTokens", 0)
            iter_out = usage.get("outputTokens", 0)
            total_tokens_in += iter_in
            total_tokens_out += iter_out
            logger.info(
                f"⏱ LLM call: {llm_elapsed:.2f}s | tokens in: {iter_in}, out: {iter_out}"
            )

            output_msg = response.get("output", {}).get("message", {})
            stop_reason = response.get("stopReason", "end_turn")
            logger.info(f"Raw API Response (stopReason={stop_reason}):")
            response_json = json_dumps_safe(output_msg, indent=2)
            if len(response_json) > 3000:
                logger.info(
                    f"{response_json[:3000]}...\n[TRUNCATED - {len(response_json)} chars total]"
                )
            else:
                logger.info(f"{response_json}")

            # Add assistant message to input_list for session/history consistency
            input_list.append({"role": "assistant", "content": output_msg})

            pending_calls = []
            for block in output_msg.get("content", []):
                if "toolUse" in block:
                    t = block["toolUse"]
                    pending_calls.append(
                        _ToolCall(
                            name=t["name"],
                            arguments=json.dumps(t.get("input") or {}),
                            call_id=t["toolUseId"],
                        )
                    )

            if stop_reason != "tool_use":
                # Extract final text from last assistant message
                final_response_text = ""
                for block in output_msg.get("content", []):
                    if "text" in block:
                        final_response_text += block.get("text", "")
                response = type(
                    "_BedrockResponse",
                    (),
                    {"output_text": final_response_text, "output": []},
                )()
        else:
            response = client.responses.create(
                model="gpt-5-mini",
                tools=tools,
                input=input_list,
                instructions=AI_INSTRUCTIONS
                + "\ntodays date is "
                + datetime.datetime.now().strftime("%Y-%m-%d"),
            )
            llm_elapsed = time.time() - llm_start
            usage = getattr(response, "usage", None)
            iter_in = getattr(usage, "input_tokens", 0) if usage else 0
            iter_out = getattr(usage, "output_tokens", 0) if usage else 0
            total_tokens_in += iter_in
            total_tokens_out += iter_out
            logger.info(
                f"⏱ LLM call: {llm_elapsed:.2f}s | tokens in: {iter_in}, out: {iter_out}"
            )
            logger.info(f"Raw API Response Output:")
            response_json = json_dumps_safe(response.output, indent=2)
            if len(response_json) > 3000:
                logger.info(
                    f"{response_json[:3000]}...\n[TRUNCATED - {len(response_json)} chars total]"
                )
            else:
                logger.info(f"{response_json}")
            input_list += response.output
            pending_calls = [
                item for item in response.output if item.type == "function_call"
            ]

        if not pending_calls:
            logger.debug("No pending function calls, breaking loop")
            # Extract the final response text from the last iteration
            final_response_text = response.output_text

            total_elapsed = time.time() - query_start
            # Compute approximate cost and usage metadata for this query
            total_cost_usd = (total_tokens_in / 1_000_000.0) * COST_INPUT_PER_1M + (
                total_tokens_out / 1_000_000.0
            ) * COST_OUTPUT_PER_1M
            model_name = BEDROCK_MODEL_ID if USE_BEDROCK else "gpt-5-mini"
            usage_meta = {
                "total_time_seconds": round(total_elapsed, 2),
                "total_cost_usd": round(total_cost_usd, 6),
                "model": model_name,
                "tokens_in": total_tokens_in,
                "tokens_out": total_tokens_out,
            }
            logger.info(f"\n{'=' * 60}")
            logger.info(f"FINAL OUTPUT")
            logger.info(f"{'=' * 60}")
            logger.info(f"Final Output Text:")
            logger.info(f"{final_response_text}")
            if chart_data:
                logger.info(
                    f"Chart Data: {chart_data.get('type', 'unknown')} chart included"
                )
            if report_data:
                logger.info(
                    f"Report Data: {len(report_data.get('reportData', []))} rows"
                )
            if pdf_data:
                logger.info(f"PDF Data: {len(pdf_data)} bytes")
            logger.info(
                f"📊 Total: {iteration_count} iterations | {total_elapsed:.2f}s | tokens in: {total_tokens_in}, out: {total_tokens_out}, total: {total_tokens_in + total_tokens_out}"
            )
            logger.info(
                f"💰 Estimated cost: ${usage_meta['total_cost_usd']} | model: {model_name}"
            )
            logger.info(f"{'=' * 60}\n")

            # Update conversation history
            add_to_session(session_id, query, final_response_text)

            logger.info(
                f"Query processed successfully, response length: {len(final_response_text)} characters"
            )
            logger.info(
                f"Session {session_id} now has {len(get_session_history(session_id))} messages in history"
            )

            # Return response with all produced payloads and usage metadata
            result = {
                "text": final_response_text,
                "type": "text",
                **usage_meta,
            }
            if chart_data:
                result["chart"] = chart_data
                result["type"] = "chart"
            if report_data:
                result["report"] = report_data
                if result["type"] == "text":
                    result["type"] = "report"
            if pdf_data:
                result["pdf"] = base64.b64encode(pdf_data).decode("ascii")
                if result["type"] == "text":
                    result["type"] = "pdf"
            return result

        logger.info(f"Processing {len(pending_calls)} function call(s)")

        tool_start = time.time()
        (
            function_outputs,
            returned_chart_data,
            returned_report_data,
            returned_pdf_data,
        ) = process_function_calls(
            pending_calls,
            schedule_headers,
            context_event_id=event_id,
            context_category_id=category_id,
        )
        tool_elapsed = time.time() - tool_start
        logger.info(f"⏱ Tool calls: {tool_elapsed:.2f}s")

        iter_elapsed = time.time() - iter_start
        logger.info(f"⏱ Iteration {iteration_count} total: {iter_elapsed:.2f}s")

        if returned_chart_data:
            chart_data = returned_chart_data
        if returned_report_data:
            report_data = returned_report_data
        if returned_pdf_data:
            pdf_data = returned_pdf_data

        # Add function outputs to input_list for next iteration
        input_list.extend(function_outputs)


def handle_query(
    query, headers, session_id=None, event_id=None, category_id=None, user_info=None
):
    """Entry point for handling queries."""
    return process_query(
        query,
        headers,
        session_id=session_id,
        event_id=event_id,
        category_id=category_id,
        user_info=user_info,
    )


if __name__ == "__main__":
    # Test queries
    db_query_15 = "Give me a complete analysis for Ford Motor: show all their events with dates, total attendees, number of decision makers, remote vs in-person count, and any associated revenue or opportunity data."

    logger.info("Running test query")
    result = handle_query(db_query_15, None)
    logger.info(f"Test query result: {result}")
