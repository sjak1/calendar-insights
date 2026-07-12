"""
Report formatting for Wijmo-style grid (reportUiConfig + reportData).
Builds table definition and row data from OpenSearch hits for frontend rendering.
"""

import datetime

# Bindings that store Unix epoch milliseconds (converted to ISO for display)
EPOCH_BINDINGS = frozenset(["event_start_time"])

# Per-binding column typing so the grid can sort/format numerically instead of
# treating everything as a String. Maps alias -> (dataType, optional wijmo format).
# dataType is one of: String, Number, Boolean, Date.
_CURRENCY_BINDINGS = frozenset(["opportunity_revenue"])
_NUMBER_BINDINGS = frozenset(["event_duration_days", "duration", "attendees"])
_DATE_BINDINGS = frozenset(["event_start_time", "start_time", "end_time"])
_BOOLEAN_BINDINGS = frozenset(["is_active", "is_remote", "decision_maker", "influencer", "technical"])


def _infer_column_meta(binding):
    """Return (dataType, format) for a binding so numbers/dates/booleans render
    and sort correctly. format is a Wijmo format string or None."""
    if binding in _CURRENCY_BINDINGS:
        return "Number", "c0"
    if binding in _NUMBER_BINDINGS:
        return "Number", "n0"
    if binding in _DATE_BINDINGS:
        return "Date", None
    if binding in _BOOLEAN_BINDINGS:
        return "Boolean", None
    return "String", None

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
    "line_of_business": "eventFormData.VISIT_INFO.lineOfBusiness",
    "region": "eventFormData.VISIT_INFO.region",
    "customer_industry": "eventFormData.VISIT_INFO.customerIndustry",
    "visit_focus": "eventFormData.VISIT_INFO.visitFocus",
    "sales_play": "eventFormData.VISIT_INFO.salesPlay",
    "customer_name": "eventFormData.VISIT_INFO.customerName",
    "opportunity_revenue": "eventFormData.Opportunity.opportunityRevenue",
    "external_attendee_last_name": "eventFormData.EXTERNAL_ATTENDEES.lastName",
    # Activity-level (when hit is activity). Nested under the `activites` field
    # on the events index; data moved activityInfo.*.data.* → activityData.*.
    "event_id": "activites.eventId",
    "activity_id": "activites.activityId",
    "activity_status": "activites.status.stateName",
    "start_time": "activites.startTime.client.clientZoneDate",
    "end_time": "activites.endTime.client.clientZoneDate",
    "duration": "activites.duration",
    "resource_name": "activites.resource.metaData.searchDisplayText",
    "presenter_name": "activites.activityData.topic_presenter.presenter.presenterName",
    "topic_name": "activites.activityData.topic.topic.textField1",
    "catering_type": "activites.activityData.CATERING.cateringType",
    "attendees": "activites.activityData.CATERING.noOfAttendees",
}


def _get_nested(obj, path):
    """Get value from nested dict by dot path. Returns None if any segment missing.
    When a segment is a list, uses the first element so paths like
    eventFormData.VISIT_INFO.customerName work when VISIT_INFO is an array."""
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
        binding = c.get("binding", c) if isinstance(c, dict) else c
        inferred_type, inferred_format = _infer_column_meta(binding)
        col = {
            "binding": binding,
            "header": c.get("header") if isinstance(c, dict) else str(c),
            # Explicit dataType/format from caller wins; otherwise infer from binding.
            "dataType": (c.get("dataType") if isinstance(c, dict) else None) or inferred_type,
        }
        fmt = (c.get("format") if isinstance(c, dict) else None) or inferred_format
        if fmt:
            col["format"] = fmt
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


def _build_group_descriptions(group_by):
    """Convert a simple list of bindings into Wijmo groupDescriptions."""
    if not group_by:
        return []
    return [{"binding": b} for b in group_by if isinstance(b, str) and b]


def _build_sort_descriptions(sort_by):
    """Convert [{binding, direction}] (or bare binding strings) into Wijmo
    sortDescriptions. direction defaults to ascending."""
    if not sort_by:
        return []
    descriptions = []
    for s in sort_by:
        if isinstance(s, str):
            descriptions.append({"binding": s, "ascending": True})
        elif isinstance(s, dict) and s.get("binding"):
            direction = str(s.get("direction", "asc")).lower()
            descriptions.append({"binding": s["binding"], "ascending": direction != "desc"})
    return descriptions


def generate_report(
    dsl_query,
    columns,
    title="Report",
    subtitle=None,
    index=None,
    max_rows=None,
    query_timezone=None,
    group_by=None,
    sort_by=None,
):
    """
    Run an OpenSearch DSL query, flatten hits to rows, and return reportUiConfig + reportData.
    Use from the generate_report tool so the LLM does not send large payloads.

    group_by: optional list of column bindings to group rows by (e.g. ["region"]).
    sort_by: optional list of {"binding": str, "direction": "asc"|"desc"} for grid sorting.
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
    return format_report(
        rows,
        columns,
        title=title,
        subtitle=subtitle,
        group_descriptions=_build_group_descriptions(group_by),
        sort_descriptions=_build_sort_descriptions(sort_by),
    )
