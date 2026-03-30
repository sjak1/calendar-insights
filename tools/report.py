"""
Report formatting for Wijmo-style grid (reportUiConfig + reportData).
Builds table definition and row data from OpenSearch hits for frontend rendering.
"""

import datetime

# Bindings that store Unix epoch milliseconds (converted to ISO for display)
EPOCH_BINDINGS = frozenset(["event_start_time"])

# Alias → dot path into _source (path without .keyword for stored doc; we try both)
REPORT_FIELD_PATHS = {
    # Event-level
    "event_id_top": "eventId",
    "event_name": "eventName",
    "status": "status.stateName",
    "category_name": "category.categoryName",
    "location_name": "location.data.locationName",
    "location_country": "location.data.country",
    "event_start_time": "startTime",
    "event_duration_days": "duration",
    "timezone": "timezone",
    "is_active": "isActive",
    "line_of_business": "eventData.VISIT_INFO.data.lineOfBusiness",
    "region": "eventData.VISIT_INFO.data.region",
    "customer_industry": "eventData.VISIT_INFO.data.customerIndustry",
    "visit_focus": "eventData.VISIT_INFO.data.visitFocus",
    "sales_play": "eventData.VISIT_INFO.data.salesPlay",
    "customer_name": "eventData.VISIT_INFO.data.customerName",
    "opportunity_revenue": "eventData.Opportunity.data.opportunityRevenue",
    "external_attendee_last_name": "eventData.EXTERNAL_ATTENDEES.data.lastName",
    # Activity-level (when hit is activity)
    "event_id": "activites.eventId",
    "activity_id": "activites.activityId",
    "activity_status": "activites.status.stateName",
    "start_time": "activites.startTime.client.clientZoneDate",
    "end_time": "activites.endTime.client.clientZoneDate",
    "duration": "activites.duration",
    "resource_name": "activites.resource.data.name",
    "presenter_name": "activites.activityInfo.topic_presenter.data.presenter.presenterName",
    "topic_name": "activites.activityInfo.topic.data.topic.textField1",
    "catering_type": "activites.activityInfo.CATERING.data.cateringType",
    "attendees": "activites.activityInfo.CATERING.data.noOfAttendees",
}


def _get_nested(obj, path):
    """Get value from nested dict by dot path. Returns None if any segment missing.
    When a segment is a list, uses the first element so paths like
    eventData.VISIT_INFO.data.customerName work when VISIT_INFO is an array."""
    if not path:
        return obj
    for key in path.split("."):
        if obj is None:
            return None
        if isinstance(obj, list):
            obj = obj[0] if obj else None
            if obj is None:
                return None
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _format_epoch_ms(ms):
    """Convert epoch milliseconds to ISO 8601 string. Returns original if invalid."""
    if ms is None:
        return None
    try:
        ts = int(ms)
        return datetime.datetime.utcfromtimestamp(ts / 1000.0).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError, OSError):
        return ms


def _format_epoch_columns(rows, bindings):
    """Format epoch-ms columns to readable strings. Mutates rows in place."""
    to_format = EPOCH_BINDINGS & set(bindings)
    if not to_format:
        return
    for row in rows:
        for b in to_format:
            val = row.get(b)
            if val is not None and isinstance(val, (int, float)):
                row[b] = _format_epoch_ms(val)


def _normalize_report_dsl_query(dsl_query):
    """
    Normalize report DSL so _source uses stored field paths, not .keyword variants.

    Filters/sorts may still legitimately use .keyword. This only rewrites the
    _source list because _source reads from stored JSON fields.
    """
    if not isinstance(dsl_query, dict):
        return dsl_query

    source_fields = dsl_query.get("_source")
    if isinstance(source_fields, list):
        normalized = []
        for field in source_fields:
            if isinstance(field, str) and field.endswith(".keyword"):
                normalized.append(field[: -len(".keyword")])
            else:
                normalized.append(field)
        dsl_query["_source"] = normalized

    return dsl_query


def flatten_source_to_row(source, bindings, field_paths=None):
    """
    Build one flat row from OpenSearch _source using alias bindings.
    bindings: list of column bindings (e.g. ["customer_name", "event_name"]).
    field_paths: alias -> dot path; defaults to REPORT_FIELD_PATHS.
    """
    paths = field_paths or REPORT_FIELD_PATHS
    row = {}
    for b in bindings:
        path = paths.get(b)
        if path is not None:
            val = _get_nested(source, path)
        else:
            val = source.get(b) if isinstance(source, dict) else None
        row[b] = val
    return row


def build_report_rows(hits, columns, max_rows=None, field_paths=None):
    """
    Convert OpenSearch run_raw_dsl hits to list of flat row dicts.
    hits: list of { "source": {...}, ... }
    columns: list of { "binding": str, "header": str (optional), "dataType": str (optional) }
    """
    bindings = [c.get("binding", c) if isinstance(c, dict) else c for c in columns]
    paths = field_paths or REPORT_FIELD_PATHS
    rows = []
    selected_hits = hits[:max_rows] if max_rows is not None else hits
    for h in selected_hits:
        source = h.get("source", h.get("_source", {}))
        row = flatten_source_to_row(source, bindings, paths)
        rows.append(row)
    return rows


def format_report(
    rows,
    columns,
    title="Report",
    subtitle=None,
    group_descriptions=None,
    sort_descriptions=None,
    filter_columns=None,
):
    """
    Build Wijmo-style reportUiConfig and reportData for the frontend.

    rows: list of flat dicts (keys = column bindings).
    columns: list of { "binding": str, "header": str (optional), "dataType": str (optional) }.
    title, subtitle: strings.
    group_descriptions / sort_descriptions / filter_columns: optional Wijmo-style arrays.

    Returns:
        dict with "type": "report", "reportUiConfig": {...}, "reportData": [...]
    """
    if not columns:
        columns = [{"binding": k, "header": k} for k in (rows[0].keys() if rows else [])]

    grid_columns = []
    for c in columns:
        col = {
            "binding": c.get("binding", c) if isinstance(c, dict) else c,
            "header": c.get("header") if isinstance(c, dict) else str(c),
            "dataType": c.get("dataType", "String"),
        }
        if col["header"] is None:
            col["header"] = col["binding"].replace("_", " ").title()
        grid_columns.append(col)

    report_ui_config = {
        "columns": grid_columns,
        "filterColumns": filter_columns or [],
        "groupDescriptions": group_descriptions or [],
        "sortDescriptions": sort_descriptions or [],
        "subtitle": subtitle or "",
        "additionalHeaderData": {},
    }

    # Ensure each row only has keys that are bindings; format epoch columns for display
    bindings_set = {col["binding"] for col in grid_columns}
    rows_copy = [dict(r) for r in rows]
    _format_epoch_columns(rows_copy, bindings_set)
    report_data = []
    for r in rows_copy:
        report_data.append({k: r.get(k) for k in bindings_set})

    return {
        "type": "report",
        "reportUiConfig": report_ui_config,
        "reportData": report_data,
    }


def generate_report(
    dsl_query,
    columns,
    title="Report",
    subtitle=None,
    index=None,
    max_rows=None,
    query_timezone=None,
):
    """
    Run an OpenSearch DSL query, flatten hits to rows, and return reportUiConfig + reportData.
    Use from the generate_report tool so the LLM does not send large payloads.
    """
    try:
        from opensearch_client import run_raw_dsl
    except ImportError:
        return {
            "type": "report",
            "reportUiConfig": {"columns": [], "filterColumns": [], "groupDescriptions": [], "sortDescriptions": [], "subtitle": "", "additionalHeaderData": {}},
            "reportData": [],
            "error": "OpenSearch client not available.",
        }

    if isinstance(dsl_query, str):
        import json as _json
        dsl_query = _json.loads(dsl_query)

    dsl_query = _normalize_report_dsl_query(dsl_query)

    result = run_raw_dsl(
        dsl_body=dsl_query,
        index=index,
        query_timezone=query_timezone,
        size_cap=None,
    )
    if not result.get("success"):
        return {
            "type": "report",
            "reportUiConfig": {"columns": [], "filterColumns": [], "groupDescriptions": [], "sortDescriptions": [], "subtitle": "", "additionalHeaderData": {}},
            "reportData": [],
            "error": result.get("error", "Search failed."),
        }

    hits = result.get("hits", [])
    rows = build_report_rows(hits, columns, max_rows=max_rows)
    return format_report(rows, columns, title=title, subtitle=subtitle)
