"""
Tool execution handlers for function calls.
"""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, date as _date, time as _time, timedelta, timezone as _timezone
from logging_config import get_logger

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None
from scripts.sqlite_qa import ask_sqlite
from tools import (
    get_gdp,
    get_report_data,
    format_chart,
    generate_agenda,
    generate_report,
    generate_pdf,
    list_rooms,
    list_event_activities,
    get_resource_schedule,
    find_vacant_slots,
    block_calendar,
)
from utils.json_utils import json_dumps_safe

try:
    from opensearch_client import (
        count as count_opensearch_fn,
        get_index_mapping as get_index_mapping_fn,
        get_suggested_presenters,
        list_indices as list_indices_fn,
        run_raw_dsl,
    )
except ImportError:
    count_opensearch_fn = None
    get_index_mapping_fn = None
    get_suggested_presenters = None
    list_indices_fn = None
    run_raw_dsl = None

logger = get_logger(__name__)

CURRENT_EVENT_PLACEHOLDER = "CURRENT_EVENT"


def _substitute_current_event(obj, real_event_id):
    """Recursively replace CURRENT_EVENT placeholder with the real event_id.

    The LLM never sees real UUIDs — it uses "CURRENT_EVENT" as a symbolic
    reference to whichever event is in focus on the page. This walker swaps
    it in place before any tool hits OpenSearch / BriefingIQ.
    """
    if not real_event_id:
        return obj
    if isinstance(obj, str):
        return real_event_id if obj == CURRENT_EVENT_PLACEHOLDER else obj
    if isinstance(obj, list):
        return [_substitute_current_event(x, real_event_id) for x in obj]
    if isinstance(obj, dict):
        return {k: _substitute_current_event(v, real_event_id) for k, v in obj.items()}
    return obj


_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?$")


def _build_time_token_map(timezone_name: str):
    """Compute epoch-ms values for sugar tokens like TODAY, THIS_WEEK_START, etc.
    All boundaries are in the user's local timezone, returned as UTC epoch ms.
    """
    try:
        tz = ZoneInfo(timezone_name) if ZoneInfo else _timezone.utc
    except Exception:
        tz = _timezone.utc

    now_local = datetime.now(tz=_timezone.utc).astimezone(tz)
    today = now_local.date()

    def sod(d):  # start-of-day epoch ms in tz
        return int(datetime.combine(d, _time(0, 0, 0), tzinfo=tz).timestamp() * 1000)

    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)
    # ISO weeks: Monday=0
    week_start = today - timedelta(days=today.weekday())
    week_end_excl = week_start + timedelta(days=7)
    next_week_start = week_end_excl
    next_week_end_excl = next_week_start + timedelta(days=7)
    month_start = today.replace(day=1)
    next_month_start = (month_start + timedelta(days=32)).replace(day=1)
    month_after_next = (next_month_start + timedelta(days=32)).replace(day=1)

    return {
        "TODAY": sod(today),
        "TODAY_START": sod(today),
        "TODAY_END": sod(tomorrow),
        "YESTERDAY_START": sod(yesterday),
        "YESTERDAY_END": sod(today),
        "TOMORROW": sod(tomorrow),
        "TOMORROW_START": sod(tomorrow),
        "TOMORROW_END": sod(today + timedelta(days=2)),
        "THIS_WEEK_START": sod(week_start),
        "THIS_WEEK_END": sod(week_end_excl),
        "NEXT_WEEK_START": sod(next_week_start),
        "NEXT_WEEK_END": sod(next_week_end_excl),
        "THIS_MONTH_START": sod(month_start),
        "THIS_MONTH_END": sod(next_month_start),
        "NEXT_MONTH_START": sod(next_month_start),
        "NEXT_MONTH_END": sod(month_after_next),
        "LAST_7_DAYS_START": sod(today - timedelta(days=7)),
        "LAST_30_DAYS_START": sod(today - timedelta(days=30)),
        "NEXT_7_DAYS_END": sod(today + timedelta(days=7)),
        "NEXT_30_DAYS_END": sod(today + timedelta(days=30)),
    }


def _iso_date_to_epoch_ms(value: str, timezone_name: str):
    """Convert ISO date or datetime string to epoch ms in the given tz, or None.

    Accepts:
      'YYYY-MM-DD'           → start-of-day in tz
      'YYYY-MM-DDTHH:MM'     → that exact minute in tz
      'YYYY-MM-DDTHH:MM:SS'  → that exact second in tz
    """
    if not isinstance(value, str):
        return None
    try:
        tz = ZoneInfo(timezone_name) if ZoneInfo else _timezone.utc
    except Exception:
        tz = _timezone.utc
    if _ISO_DATETIME_RE.match(value):
        try:
            dt = datetime.fromisoformat(value.replace(" ", "T"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
            return int(dt.timestamp() * 1000)
        except ValueError:
            return None
    if _ISO_DATE_RE.match(value):
        try:
            d = _date.fromisoformat(value)
            return int(datetime.combine(d, _time(0, 0, 0), tzinfo=tz).timestamp() * 1000)
        except ValueError:
            return None
    return None


def _substitute_time_tokens(obj, timezone_name: str, token_map=None):
    """Walk a DSL dict and replace time placeholders with epoch-ms numbers.

    Replaces in place:
      - sugar tokens like TODAY, THIS_WEEK_START → epoch_ms (from token_map)
      - ISO date strings 'YYYY-MM-DD' → start-of-day epoch_ms in user tz

    Lets the LLM author DSL in human-readable date terms while OpenSearch
    receives the epoch_millis numbers it needs.
    """
    if token_map is None:
        token_map = _build_time_token_map(timezone_name)
    if isinstance(obj, str):
        if obj in token_map:
            return token_map[obj]
        epoch = _iso_date_to_epoch_ms(obj, timezone_name)
        return epoch if epoch is not None else obj
    if isinstance(obj, list):
        return [_substitute_time_tokens(x, timezone_name, token_map) for x in obj]
    if isinstance(obj, dict):
        return {k: _substitute_time_tokens(v, timezone_name, token_map) for k, v in obj.items()}
    return obj


def _get_query_timezone(schedule_headers=None) -> str:
    """Pick the best timezone available for relative-date OpenSearch queries."""
    headers = schedule_headers or {}
    return (
        headers.get("x-cloud-requested-timezone")
        or headers.get("requested-timezone")
        or headers.get("x-cloud-context-timezone")
        or headers.get("context-timezone")
        or headers.get("x-cloud-client-timezone")
        or headers.get("client-timezone")
        or "America/Los_Angeles"
    )


_MAX_TOOL_OUTPUT_CHARS = 30_000  # ~7.5k tokens — keeps LLM context under control


def _trim_search_hits(result, max_chars=_MAX_TOOL_OUTPUT_CHARS):
    """Trim oversized search results so the LLM doesn't get a 500k char context bomb.

    Strategy: keep aggregations intact (small), truncate hits by dropping
    large nested fields and capping the number of hits returned to the LLM.
    """
    if not isinstance(result, dict) or "hits" not in result:
        return result

    output_str = json.dumps(result, default=str)
    if len(output_str) <= max_chars:
        return result

    hits = result.get("hits", [])
    aggs = result.get("aggregations")

    # First pass: slim each hit's source by dropping deep nested arrays
    slimmed_hits = []
    for h in hits:
        src = h.get("source", {})
        slim_src = {}
        for k, v in src.items():
            serialized = json.dumps(v, default=str)
            if len(serialized) > 2000:
                # Summarize large nested arrays (e.g. activityDays with dozens of activities)
                if isinstance(v, list):
                    slim_src[k] = f"[{len(v)} items — truncated]"
                elif isinstance(v, dict):
                    slim_src[k] = {sk: sv for sk, sv in v.items() if len(json.dumps(sv, default=str)) < 500}
                    slim_src[k]["_truncated"] = True
                else:
                    slim_src[k] = v
            else:
                slim_src[k] = v
        slimmed_hits.append({**h, "source": slim_src})

    trimmed = {**result, "hits": slimmed_hits}

    # Second pass: if still too big, reduce number of hits
    output_str = json.dumps(trimmed, default=str)
    while len(output_str) > max_chars and len(trimmed["hits"]) > 5:
        trimmed["hits"] = trimmed["hits"][: len(trimmed["hits"]) // 2]
        trimmed["_note"] = f"Showing {len(trimmed['hits'])} of {result.get('total_hits', '?')} hits (trimmed for context size)"
        output_str = json.dumps(trimmed, default=str)

    return trimmed


def _summarize_report_for_llm(report_payload):
    """Keep report tool output compact; frontend still receives full payload separately."""
    report_ui_config = report_payload.get("reportUiConfig", {}) if isinstance(report_payload, dict) else {}
    report_rows = report_payload.get("reportData", []) if isinstance(report_payload, dict) else []
    columns = report_ui_config.get("columns", []) if isinstance(report_ui_config, dict) else []
    sample_row = report_rows[0] if report_rows else None

    return {
        "type": "report",
        "rowCount": len(report_rows),
        "columns": [
            {
                "binding": col.get("binding"),
                "header": col.get("header"),
            }
            for col in columns
        ],
        "subtitle": report_ui_config.get("subtitle", ""),
        "sampleRow": sample_row,
        "error": report_payload.get("error") if isinstance(report_payload, dict) else None,
    }


def execute_tool(
    tool_name,
    args,
    schedule_headers=None,
    context_event_id=None,
    context_category_id=None,
):
    """
    Execute a tool function and return the output.

    Args:
        tool_name: Name of the tool to execute
        args: Arguments for the tool
        schedule_headers: Optional headers for BriefingIQ API calls
        context_event_id: Optional event ID from header (for context-aware operations)
        context_category_id: Optional category ID from header (for category-scoped queries)

    Returns:
        Dict with tool output or error
    """
    try:
        if context_event_id and isinstance(args, dict):
            args = _substitute_current_event(args, context_event_id)

        if tool_name == "get_gdp":
            result = get_gdp(args["country"], args["year"])
            output = {"gdp": result}
            logger.info(f"✓ {tool_name} returned: {json.dumps(output, indent=2)}")
            return output

        elif tool_name == "list_rooms":
            token = (schedule_headers or {}).get("Authorization", "")
            event_id = args.get("event_id") or context_event_id or ""
            result = list_rooms(token, schedule_headers, event_id=event_id)
            output = {"list_rooms": result}
            logger.info(f"✓ {tool_name} returned {len(result)} rooms (event_id={event_id or 'none'})")
            return output

        elif tool_name == "list_event_activities":
            token = (schedule_headers or {}).get("Authorization", "")
            event_id = args.get("event_id") or context_event_id or ""
            date = args.get("date") or None
            result = list_event_activities(token, schedule_headers, event_id=event_id, date=date)
            output = {"list_event_activities": result}
            logger.info(f"✓ {tool_name} returned {len(result)} activities (event={event_id or 'none'}, date={date or 'all'})")
            return output

        elif tool_name == "get_resource_schedule":
            token = (schedule_headers or {}).get("Authorization", "")
            result = get_resource_schedule(args["resource_id"], token, schedule_headers)
            output = {"get_resource_schedule": result}
            logger.info(f"✓ {tool_name} returned {len(result)} entries")
            return output

        elif tool_name == "find_vacant_slots":
            token = (schedule_headers or {}).get("Authorization", "")
            result = find_vacant_slots(
                resource_id=args["resource_id"],
                date=args["date"],
                duration_minutes=args["duration_minutes"],
                token=token,
                schedule_headers=schedule_headers,
                day_start_hour=args.get("day_start_hour", 9),
                day_end_hour=args.get("day_end_hour", 18),
            )
            output = {"find_vacant_slots": result}
            logger.info(f"✓ {tool_name} returned {len(result)} free slots")
            return output

        elif tool_name == "block_calendar":
            token = (schedule_headers or {}).get("Authorization", "")
            result = block_calendar(
                resource_id=args["resource_id"],
                start_iso=args["start_iso"],
                end_iso=args["end_iso"],
                token=token,
                schedule_headers=schedule_headers,
                comments=args.get("comments"),
                calendar_type=args.get("calendar_type", "BLOCKED"),
            )
            output = {"block_calendar": result}
            logger.info(f"✓ {tool_name} returned: {json.dumps(output)[:300]}")
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
                logger.info(
                    f"✓ {tool_name} returned: {output_str[:500]}... (truncated, {len(output_str)} chars total)"
                )
            else:
                logger.info(f"✓ {tool_name} returned: {output_str}")
            return output

        elif tool_name == "query_database":
            result = ask_sqlite(args["question"])
            # Redact raw SQL from tool output so the LLM never exposes it to the user
            result_for_llm = {k: v for k, v in result.items() if k != "sql"}
            output = {"query_database": result_for_llm}
            output_str = json.dumps(output, indent=2, default=str)
            if len(output_str) > 1000:
                logger.info(
                    f"✓ {tool_name} returned: {output_str[:1000]}... (truncated, {len(output_str)} chars total)"
                )
            else:
                logger.info(f"✓ {tool_name} returned: {output_str}")
            return output

        elif tool_name == "search_opensearch":
            if run_raw_dsl is None:
                output = {"error": "OpenSearch client not available (opensearch-py not installed or OPENSEARCH_URL not set)."}
            else:
                timezone_name = _get_query_timezone(schedule_headers)
                if args.get("dsl_query") is None:
                    output = {"error": "search_opensearch now requires dsl_query."}
                else:
                    dsl = args.get("dsl_query")
                    if isinstance(dsl, str):
                        import json as _json
                        dsl = _json.loads(dsl)
                    dsl = _substitute_time_tokens(dsl, timezone_name)
                    result = run_raw_dsl(
                        dsl_body=dsl,
                        index=args.get("index"),
                        query_timezone=timezone_name,
                    )
                    output = {"search_opensearch": _trim_search_hits(result)}
            output_str = json.dumps(output, indent=2, default=str)
            if len(output_str) > 1500:
                logger.info(f"✓ {tool_name} returned: {output_str[:1500]}... (truncated)")
            else:
                logger.info(f"✓ {tool_name} returned: {output_str}")
            return output

        elif tool_name == "count_opensearch":
            if count_opensearch_fn is None:
                output = {"error": "OpenSearch client not available."}
            else:
                q = args.get("query")
                if isinstance(q, str):
                    import json as _json
                    q = _json.loads(q)
                # Unwrap if LLM passed full body { "query": { "bool": ... } } to avoid double-wrapping
                if isinstance(q, dict) and list(q.keys()) == ["query"] and isinstance(q.get("query"), dict):
                    q = q["query"]
                if q:
                    timezone_name = _get_query_timezone(schedule_headers)
                    q = _substitute_time_tokens(q, timezone_name)
                result = count_opensearch_fn(index=args.get("index"), body={"query": q} if q else {})
                output = {"count_opensearch": result}
            logger.info(f"✓ count_opensearch returned: {output.get('count_opensearch', {}).get('count', output.get('error'))}")
            return output

        elif tool_name == "get_time_context":
            # Provide a reliable source of "now" and day boundary epoch-ms for date filtering.
            from datetime import datetime, date, time, timedelta, timezone as _timezone

            timezone_name = (args or {}).get("timezone") or _get_query_timezone(schedule_headers)
            try:
                from zoneinfo import ZoneInfo  # py3.9+
                tz = ZoneInfo(timezone_name)
            except Exception:
                tz = _timezone.utc
                timezone_name = "UTC"

            now_utc = datetime.now(tz=_timezone.utc)
            now_local = now_utc.astimezone(tz)

            _args = args or {}
            date_iso = _args.get("date_iso")
            if date_iso:
                # Expected YYYY-MM-DD
                target_date = date.fromisoformat(str(date_iso))
            else:
                target_date = now_local.date()

            # How many consecutive days to compute (including base date)
            days_ahead_raw = _args.get("days_ahead", 1)
            try:
                days_ahead = int(days_ahead_raw)
            except Exception:
                days_ahead = 1
            if days_ahead < 1:
                days_ahead = 1

            days_payload = []
            for offset in range(days_ahead):
                d = target_date + timedelta(days=offset)
                start_local = datetime.combine(d, time(0, 0, 0), tzinfo=tz)
                end_local = start_local + timedelta(days=1)

                start_utc = start_local.astimezone(_timezone.utc)
                end_utc = end_local.astimezone(_timezone.utc)

                days_payload.append(
                    {
                        "date_iso": d.isoformat(),
                        "start_of_day_local_iso": start_local.isoformat(),
                        "end_of_day_local_iso": end_local.isoformat(),
                        "start_of_day_utc_iso": start_utc.isoformat(),
                        "end_of_day_utc_iso": end_utc.isoformat(),
                        "start_of_day_utc_epoch_ms": int(start_utc.timestamp() * 1000),
                        "end_of_day_utc_epoch_ms": int(end_utc.timestamp() * 1000),
                    }
                )

            # Backwards-compatible top-level fields for single-day usage
            first_day = days_payload[0]
            output = {
                "get_time_context": {
                    "timezone": timezone_name,
                    "now_utc_iso": now_utc.isoformat(),
                    "now_local_iso": now_local.isoformat(),
                    "date_iso": first_day["date_iso"],
                    "start_of_day_local_iso": first_day["start_of_day_local_iso"],
                    "end_of_day_local_iso": first_day["end_of_day_local_iso"],
                    "start_of_day_utc_iso": first_day["start_of_day_utc_iso"],
                    "end_of_day_utc_iso": first_day["end_of_day_utc_iso"],
                    "start_of_day_utc_epoch_ms": first_day["start_of_day_utc_epoch_ms"],
                    "end_of_day_utc_epoch_ms": first_day["end_of_day_utc_epoch_ms"],
                    "days": days_payload,
                }
            }
            logger.info(
                f"✓ get_time_context returned {len(days_payload)} day(s) starting {first_day['date_iso']} tz {timezone_name}"
            )
            return output

        elif tool_name == "list_indices":
            if list_indices_fn is None:
                output = {"error": "OpenSearch client not available."}
            else:
                result = list_indices_fn(
                    index=args.get("index"),
                    include_detail=args.get("include_detail", True),
                )
                output = {"list_indices": result}
            logger.info(f"✓ list_indices returned {len(output.get('list_indices', {}).get('indices', []))} indices")
            return output

        elif tool_name == "get_index_mapping":
            if get_index_mapping_fn is None:
                output = {"error": "OpenSearch client not available."}
            else:
                result = get_index_mapping_fn(index=args.get("index", ""))
                output = {"get_index_mapping": result}
            logger.info(f"✓ get_index_mapping returned for index: {args.get('index')}")
            return output

        elif tool_name == "format_chart":
            result = format_chart(
                args["chart_type"],
                args["title"],
                args.get("x_axis_data") or [],
                args.get("series_data") or [],
                args.get("y_axis_title"),
                args.get("stacking"),
                args.get("subtitle"),
                args.get("heatmap_data"),
                args.get("y_axis_data"),
                args.get("xrange_data"),
                args.get("xrange_categories"),
            )
            output = {"format_chart": result}
            logger.info(
                f"✓ {tool_name} returned Highcharts config for ''{args['chart_type']}' chart"
            )
            return output, result  # Return both output and chart_data

        elif tool_name == "generate_pdf":
            pdf_bytes = generate_pdf(
                content=args.get("content", ""),
                title=args.get("title", "Document"),
            )
            output = {"generate_pdf": {"success": True, "size_bytes": len(pdf_bytes)}}
            logger.info(f"✓ {tool_name} returned PDF ({len(pdf_bytes)} bytes)")
            return output, pdf_bytes

        elif tool_name == "generate_report":
            result = generate_report(
                args["dsl_query"],
                args["columns"],
                title=args.get("title", "Report"),
                subtitle=args.get("subtitle"),
                index=args.get("index"),
                query_timezone=_get_query_timezone(schedule_headers),
            )
            output = {"generate_report": _summarize_report_for_llm(result)}
            logger.info(
                f"✓ {tool_name} returned report with {len(result.get('reportData', []))} rows"
            )
            return output, result  # Return both output and report payload for frontend

        elif tool_name == "generate_agenda":
            # Priority: context_event_id (from header) > args.event_id (from LLM)
            llm_event_id = args.get("event_id")
            effective_event_id = context_event_id or llm_event_id

            if context_event_id:
                logger.info(f"🎯 Prioritizing event_id from header: {context_event_id}")
                if llm_event_id and llm_event_id != context_event_id:
                    logger.info(
                        f"   (LLM extracted: {llm_event_id}, but using header value)"
                    )
            elif llm_event_id:
                logger.info(
                    f"📝 Using LLM-extracted event_id: {llm_event_id} (no header event_id)"
                )
            else:
                logger.info(
                    f"ℹ️  No event_id available, using company_name: {args.get('company_name')}"
                )

            result = generate_agenda(
                event_id=effective_event_id, company_name=args.get("company_name")
            )
            output = {"generate_agenda": result}
            output_str = json_dumps_safe(output, indent=2)
            # Generate agenda returns a lot of data, so truncate more aggressively
            if len(output_str) > 2000:
                logger.info(
                    f"✓ {tool_name} returned:\n{output_str[:2000]}...\n[TRUNCATED - {len(output_str)} chars total]"
                )
            else:
                logger.info(f"✓ {tool_name} returned:\n{output_str}")
            return output

        elif tool_name == "get_event_rooms":
            # Legacy alias — routes through merged list_rooms
            token = (schedule_headers or {}).get("Authorization", "")
            event_id = context_event_id or args.get("event_id", "")
            result = list_rooms(token, schedule_headers, event_id=event_id)
            output = {"get_event_rooms": {"rooms": result, "count": len(result)}}
            logger.info(f"✓ get_event_rooms (via list_rooms) returned {len(result)} rooms")
            return output

        elif tool_name == "push_agenda_to_briefingiq":
            from tools.briefingiq_writer import push_agenda_to_app
            token = (schedule_headers or {}).get("Authorization", "")
            effective_event_id = context_event_id or args["event_id"]
            result = push_agenda_to_app(
                event_id=effective_event_id,
                event_date=args["event_date"],
                sessions=args["sessions"],
                token=token,
                presenter_emails=args.get("presenter_emails"),
                resource_id=args.get("resource_id"),
                schedule_headers=schedule_headers,
            )
            output = {"push_agenda_to_briefingiq": result}
            logger.info(f"✓ push_agenda_to_briefingiq: {result.get('created_count', 0)} created, {result.get('failed_count', 0)} failed")
            return output

        elif tool_name == "suggest_presenters":
            if get_suggested_presenters is None:
                output = {"suggest_presenters": {"success": False, "error": "OpenSearch client not available.", "suggested_presenters": []}}
            else:
                limit = args.get("limit")
                if limit is not None:
                    limit = max(1, min(50, int(limit)))
                else:
                    limit = 10
                # Resolve time-token strings → epoch_ms for availability window
                tz_name = _get_query_timezone(schedule_headers)
                def _resolve_ms(val):
                    if val is None:
                        return None
                    if isinstance(val, (int, float)):
                        return int(val)
                    if isinstance(val, str):
                        token_map = _build_time_token_map(tz_name)
                        if val in token_map:
                            return token_map[val]
                        epoch = _iso_date_to_epoch_ms(val, tz_name)
                        return epoch
                    return None

                result = get_suggested_presenters(
                    topic=args.get("topic"),
                    industry=args.get("industry"),
                    customer_name=args.get("customer_name"),
                    event_id=args.get("event_id") or context_event_id,
                    audience_level=args.get("audience_level"),
                    limit=limit,
                    check_start_utc_ms=_resolve_ms(args.get("check_start_utc_ms")),
                    check_end_utc_ms=_resolve_ms(args.get("check_end_utc_ms")),
                )
                output = {"suggest_presenters": result}
            logger.info(f"✓ suggest_presenters returned {len(output.get('suggest_presenters', {}).get('suggested_presenters', []))} presenters")
            return output

        else:
            logger.warning(f"Unknown tool: {tool_name}")
            return {"error": f"Unknown tool: {tool_name}"}

    except Exception as e:
        logger.error(f"✗ Error in {tool_name}: {e}", exc_info=True)
        return {"error": str(e)}


def process_function_calls(
    pending_calls,
    schedule_headers=None,
    context_event_id=None,
    context_category_id=None,
    on_event=None,
):
    """
    Process a list of function calls and return results.

    Args:
        pending_calls: List of function calls to process
        schedule_headers: Optional headers for BriefingIQ API calls
        context_event_id: Optional event ID from header (for context-aware operations)
        context_category_id: Optional category ID from header (for category-scoped queries)
        on_event: Optional callback(event_type, payload_dict) for live-progress streaming.
                  Called from worker threads, so it must be thread-safe (a queue.put works).

    Returns:
        Tuple of (function_call_outputs, chart_data, report_data, pdf_data)
        chart_data / report_data / pdf_data are None if not produced
    """
    chart_data = None
    report_data = None
    pdf_data = None

    def _emit(ev_type, **data):
        if on_event is not None:
            try:
                on_event(ev_type, data)
            except Exception:
                pass  # never let a broken listener break the pipeline

    def _run(item):
        args = json.loads(item.arguments) if item.arguments else {}
        args_str = json.dumps(args, indent=2, ensure_ascii=False)
        logger.info(f"→ Calling function: {item.name} with args:\n{args_str}")
        t0 = time.time()
        _emit("tool_start", name=item.name, call_id=item.call_id, args_preview=args_str[:400])
        result = execute_tool(
            item.name,
            args,
            schedule_headers,
            context_event_id=context_event_id,
            context_category_id=context_category_id,
        )
        duration = time.time() - t0
        logger.info(f"   ↳ {item.name} finished in {duration:.2f}s")
        _emit("tool_end", name=item.name, call_id=item.call_id, duration=round(duration, 3))
        return item, result

    # Single tool → just run inline (no thread-pool overhead).
    # Multiple tools → fan out: tool handlers are self-contained + I/O-bound,
    # so a thread pool turns the total latency into max(tool_time) instead of sum(tool_time).
    if len(pending_calls) == 1:
        results = [_run(pending_calls[0])]
    else:
        with ThreadPoolExecutor(max_workers=min(len(pending_calls), 5)) as ex:
            results = list(ex.map(_run, pending_calls))

    # Preserve LLM's original call order in the outputs (some providers care).
    function_outputs = []
    for item, result in results:
        if isinstance(result, tuple):
            output, payload = result
            if item.name == "format_chart":
                chart_data = payload
            elif item.name == "generate_report":
                report_data = payload
            elif item.name == "generate_pdf":
                pdf_data = payload  # bytes
        else:
            output = result

        function_outputs.append(
            {
                "type": "function_call_output",
                "call_id": item.call_id,
                "output": json_dumps_safe(output),
            }
        )

    return function_outputs, chart_data, report_data, pdf_data
