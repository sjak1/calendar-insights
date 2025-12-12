from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv
from openai import OpenAI
from sqlalchemy import create_engine, inspect, text
import sys
import os
import datetime

# Add parent directory to path for logging_config import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logging_config import get_logger

load_dotenv()

logger = get_logger(__name__)



ORACLE_CONNECTION_URI = (
    "oracle+oracledb://BIQ_EIQ_AURORA:BIQ_EIQ_AURORA"
    "@biqdb.ciqohztp4uck.us-west-2.rds.amazonaws.com:1521/?service_name=ORCL"
)

engine = create_engine(ORACLE_CONNECTION_URI)
SCHEMA_CACHE: str | None = None

# Views exposed through this helper (these are the only ones the user mentioned)
VIEW_NAMES = [
    "VW_OPERATIONS_REPORT",
    "VW_ATTENDEE_REPORT",
    "VW_OPP_TRACKING_REPORT",
]

# Context messages to help the model pick the right view
VIEW_CONTEXTS: Dict[str, str] = {
    "VW_OPERATIONS_REPORT": """
 **OPERATIONS REPORT VIEW** — Operations snapshot for events.
- Event metadata: EVENTID, CUSTOMERNAME, PRIMARYOPPORTUNITY, SECONDARYOPPORTUNITY.
- Scheduling: STARTDATEMS, STARTTIMEMS, ENDTIMEMS, ACTSTARTTIMEMS( Use this for "meetings today", "meetings this week", etc.), ACTENDTIMEMS (epoch ms values).
- Logistics & ownership: REQUESTEREMAIL, ORACLEHOSTNAME/EMAIL/CELLPHONE, TECHMANAGER,
  BACKUPTECHMANAGER, BRIEFINGMANAGER, PROGRAM, COSTCENTER.
- Other descriptors: FORMTYPE, PILLARS, ACCOUNTTYPE, LINEOFBUSINESS, VISITFOCUS, REGION, TIER.
- Convert epoch ms to DATE before compare/order: DATE '1970-01-01' + NUMTODSINTERVAL(startdatems/1000,'SECOND').
  Example for today: TRUNC(DATE '1970-01-01' + NUMTODSINTERVAL(startdatems/1000,'SECOND')) = TRUNC(SYSDATE).

Use for operational details and high-level event summaries.
""",
    "VW_ATTENDEE_REPORT": """
**ATTENDEE REPORT VIEW** — Attendee roster per event.
- Event metadata: EVENTID, CUSTOMERNAME, PRIMARYOPPORTUNITY, SECONDARYOPPORTUNITY.
- Scheduling info via epoch milliseconds: STARTDATEMS, STARTTIMEMS, ENDTIMEMS.
- Attendee attributes: ATTENDEETYPE, ISREMOTE, TRANSLATOR, DECISIONMAKER(Yes, No), INFLUENCER(Yes, No), ISTECHNICAL(Yes, No).
- Personal/contact info: FIRSTNAME, LASTNAME, EMAIL, PREFIX, BUSINESSTITLE, CHIEFOFFICERTITLE, COMPANY.
- Convert ms values to DATE before comparing to SYSDATE / ranges.

Use for attendee lists, roles, remote/in-person breakdowns.
""",
    "VW_OPP_TRACKING_REPORT": """
**OPPORTUNITY TRACKING VIEW** — Revenue & pipeline metrics tied to events.
- Event metadata overlaps with operations: EVENTID, CUSTOMERNAME, STARTTIMEMS, ENDTIMEMS, ACTSTARTTIMEMS, ACTENDTIMEMS.
- Opportunity metrics: OPPNUMBER, STATUS, PROBABILITYOFCLOSE(ex: 75% , 90%), QUARTEROFCLOSE, OPENDATE, CLOSEDATE.
- Revenue: INITIALOPPORTUNITYREVENUE, OPENOPPREVENUE, CLOSED_OPPORTUNITY_REVENUE,
  CHANGEINREVENUEDOLLAR, CHANGEINREVENUEPERCENT.
- Context: FORMTYPE, PILLARS, ACCOUNTTYPE, LINEOFBUSINESS, REGION, PROGRAM, TIER, COSTCENTER.
- For dates/times, rely on *_MS fields or OPENDATE/CLOSEDATE strings; convert ms to DATE before comparisons.

Use when the question mentions revenue, pipeline, or opportunity tracking.
""",
}

BASE_ORACLE_RULES = """
CRITICAL ORACLE SQL RULES
- NEVER end statements with a semicolon.
- Use FETCH FIRST n ROWS ONLY or WHERE ROWNUM <= n (no LIMIT).
- for epoch-ms → date conversion, never use numtodsinterval bc it explodes on large values.
  instead do:
    date '1970-01-01' + (epoch_ms/1000)/86400
- example month filter:
    trunc(date '1970-01-01' + (startdatems/1000)/86400, 'mm') = trunc(sysdate, 'mm')
- use ACTSTARTTIMEMS and ACTENDTIMEMS for "meetings today", "meetings this week", etc.
- Strings use single quotes.
- Only generate SELECT queries.
- Case-insensitive substring search: use lower(column) like '%term%' to catch variations in casing/spelling
   example: where lower(customername) like '%grand hotel%' 
            or lower(companyname) like '%grand hotel%'
"""


def _call_llm(messages: List[Dict[str, str]]) -> str:
    """
    Call the OpenAI API, supporting both the new Responses API and the legacy
    Chat Completions API depending on the installed SDK version.
    """
    client = OpenAI()

    # Prefer Responses API if available (newer SDKs)
    responses_api = getattr(client, "responses", None)
    if responses_api is not None:
        response = responses_api.create(
            model="gpt-4.1-mini",
            input=messages,
            text={"format": {"type": "json_object"}},
            instructions="todays date is " + datetime.datetime.now().strftime("%Y-%m-%d")
        )
        return response.output_text

    # Fallback to Chat Completions API (older SDKs)
    chat_completions = getattr(client, "chat", None)
    if chat_completions is None or not hasattr(chat_completions, "completions"):
        raise RuntimeError("OpenAI client does not support responses or chat completions APIs.")

    response = chat_completions.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content)
    return content


def _load_schema() -> str:
    """
    Generate and cache schema + context information for the views.
    """
    global SCHEMA_CACHE
    if SCHEMA_CACHE is not None:
        logger.debug("Using cached schema")
        return SCHEMA_CACHE

    logger.info("Loading schema from database")
    inspector = inspect(engine)
    schema_lines: List[str] = []

    for view_name in VIEW_NAMES:
        try:
            columns = inspector.get_columns(view_name)
            if not columns:
                logger.warning(f"No columns found for view: {view_name}")
                continue
            filtered_columns = [
                col for col in columns if "CLOUD_DATE" not in str(col["type"]).upper()
            ]
            column_defs = ", ".join(
                f"{col['name']} ({col['type']})" for col in filtered_columns
            )
            schema_lines.append(f"{view_name}: {column_defs}")
            context = VIEW_CONTEXTS.get(view_name)
            if context:
                schema_lines.append(f"Context:\n{context.strip()}\n")
            logger.debug(f"Loaded schema for view: {view_name} ({len(filtered_columns)} columns)")
        except Exception as e:
            logger.error(f"Error loading schema for view {view_name}: {e}", exc_info=True)

    SCHEMA_CACHE = "\n".join(schema_lines)
    logger.info(f"Schema loaded successfully, total length: {len(SCHEMA_CACHE)} characters")
    return SCHEMA_CACHE


def _generate_sql(question: str) -> Tuple[str, str]:
    """
    Ask the model for an Oracle-ready SQL statement and a plain-language explanation.
    """
    logger.info(f"Generating SQL for question: {question[:100]}...")
    schema = _load_schema()
    system_prompt = (
        "You are an Oracle SQL expert. "
        "Answer the question by returning a JSON object with 'sql' and 'explanation'.\n"
        f"{BASE_ORACLE_RULES}\n"
        f"Schema & context:\n{schema}"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]
    try:
        content = _call_llm(messages)
        if not content or not content.strip():
            logger.error("LLM returned empty response")
            raise ValueError("LLM returned empty response")
        
        logger.debug(f"LLM response content (first 500 chars): {content[:500]}")
        payload = json.loads(content)

        sql = payload.get("sql", "").strip()
        explanation = payload.get("explanation", "")

        sql = sql.rstrip(";")
        lowered = sql.lower()
        if sql and "fetch first" not in lowered and "rownum" not in lowered:
            sql += "\nFETCH FIRST 100 ROWS ONLY"

        logger.debug(f"Generated SQL: {sql}")
        logger.info("SQL generation completed successfully")
        return sql, explanation
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response as JSON: {e}")
        logger.error(f"Response content that failed to parse: {content[:1000] if 'content' in locals() else 'N/A'}")
        raise
    except Exception as e:
        logger.error(f"Error generating SQL: {e}", exc_info=True)
        raise


def _execute_sql(sql: str) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    Run the SQL statement against Oracle and return rows + column names.
    """
    logger.info(f"Executing SQL query (length: {len(sql)} characters)")
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            rows = result.fetchall()
            columns = result.keys()
            data = [dict(zip(columns, row)) for row in rows]
        logger.info(f"SQL query executed successfully, returned {len(data)} rows")
        return list(columns), data
    except Exception as e:
        logger.error(f"Error executing SQL: {e}", exc_info=True)
        logger.debug(f"Failed SQL query: {sql}")
        raise


def ask_sqlite(question: str) -> Dict[str, Any]:
    """
    Legacy entry point: answer a question using the Oracle views. Retains the
    old function name for compatibility with existing callers.
    """
    logger.info(f"Processing question via ask_sqlite: {question[:100]}...")
    sql, explanation = _generate_sql(question)
    if not sql:
        logger.warning("No SQL generated for question")
        return {
            "sql": sql,
            "explanation": explanation or "Could not generate SQL for the question.",
            "rows": [],
        }

    try:
        columns, data = _execute_sql(sql)
    except Exception as exc:  # pragma: no cover - runtime safeguard
        logger.error(f"SQL execution failed: {exc}", exc_info=True)
        return {
            "sql": sql,
            "explanation": f"{explanation}\nOracle error: {exc}",
            "rows": [],
        }

    logger.info(f"Question processed successfully, returning {len(data)} rows")
    return {
        "sql": sql,
        "explanation": explanation,
        "columns": columns,
        "rows": data,
    }
