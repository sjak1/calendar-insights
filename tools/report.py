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
_BOOLEAN_BINDINGS = frozenset(
    ["is_active", "is_remote", "decision_maker", "influencer", "technical", "is_technical"]
)

# Row-expand registry: fan one event hit into one row per nested array element
# (e.g. one row per attendee). Bindings listed in an entry's item_fields resolve
# against each array element; all other bindings resolve against the event hit.
# NOTE: item field paths are seeded from known attendee shapes and should be
# validated against live OpenSearch data before relying on every column.
_ATTENDEE_ITEM_FIELDS = {
    "attendee_name": "attendeeName",
    "attendee_first_name": "firstName",
    "attendee_last_name": "lastName",
    "attendee_title": "businessTitle",
    "attendee_email": "email",
    "attendee_company": "company",
    "attendee_prefix": "prefix",
    "chief_officer_title": "chiefOfficerTitle",
    "is_remote": "isRemote",
    "decision_maker": "decisionMaker",
    "is_technical": "isTechnical",
    "influencer": "influencer",
}

# Synthetic binding: not read from the item — stamped with the source list's
# label ("Internal"/"External") so mixed reports can show/group by attendee type.
ATTENDEE_TYPE_BINDING = "attendee_type"

# Each entry lists (path, type_label) pairs; rows are emitted in pair order
# (Internal before External, matching the native grid).
ROW_EXPAND = {
    "external_attendees": {
        "paths": [("eventFormData.EXTERNAL_ATTENDEES", "External")],
        "item_fields": _ATTENDEE_ITEM_FIELDS,
    },
    "internal_attendees": {
        "paths": [("eventFormData.INTERNAL_ATTENDEES", "Internal")],
        "item_fields": _ATTENDEE_ITEM_FIELDS,
    },
    "all_attendees": {
        "paths": [
            ("eventFormData.INTERNAL_ATTENDEES", "Internal"),
            ("eventFormData.EXTERNAL_ATTENDEES", "External"),
        ],
        "item_fields": _ATTENDEE_ITEM_FIELDS,
    },
}


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


def _get_list(obj, path):
    """Traverse a dot path and return the list found at the end (or [] if none).
    Unlike _get_nested, this does not collapse the final list to its first item."""
    for key in path.split("."):
        if isinstance(obj, list):
            obj = obj[0] if obj else None
        if not isinstance(obj, dict):
            return []
        obj = obj.get(key)
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        return [obj]
    return []


def _expand_hit_to_rows(source, bindings, expand_cfg, paths):
    """Fan one event source into one row per nested array element.

    Event-level bindings are resolved once from the hit; item-level bindings
    (those in expand_cfg.item_fields) are resolved per element; the synthetic
    attendee_type binding is stamped with the source list's label. An event
    with no elements still yields one row (item columns null) so it isn't
    dropped. Multiple source lists (e.g. internal + external attendees) are
    concatenated in configured order.
    """
    item_fields = expand_cfg.get("item_fields", {})
    special = {ATTENDEE_TYPE_BINDING}
    event_bindings = [b for b in bindings if b not in item_fields and b not in special]
    item_bindings = [b for b in bindings if b in item_fields]
    want_type = ATTENDEE_TYPE_BINDING in bindings
    base_row = flatten_source_to_row(source, event_bindings, paths)

    labeled_items = []
    for list_path, type_label in expand_cfg["paths"]:
        for item in _get_list(source, list_path):
            labeled_items.append((item, type_label))

    if not labeled_items:
        row = dict(base_row)
        for b in item_bindings:
            row[b] = None
        if want_type:
            row[ATTENDEE_TYPE_BINDING] = None
        return [row]

    rows = []
    for item, type_label in labeled_items:
        row = dict(base_row)
        for b in item_bindings:
            row[b] = _get_nested(item, item_fields[b]) if isinstance(item, dict) else None
        # INTERNAL_ATTENDEES items carry no attendeeName — compose it from
        # prefix + firstName + lastName so both types render a name.
        if "attendee_name" in item_bindings and not row.get("attendee_name") and isinstance(item, dict):
            composed = " ".join(
                p for p in (item.get("prefix"), item.get("firstName"), item.get("lastName")) if p
            )
            row["attendee_name"] = composed or None
        if want_type:
            row[ATTENDEE_TYPE_BINDING] = type_label
        rows.append(row)
    return rows


def build_report_rows(hits, columns, max_rows=None, field_paths=None, expand=None):
    """
    Convert OpenSearch run_raw_dsl hits to list of flat row dicts.
    hits: list of { "source": {...}, ... }
    columns: list of { "binding": str, "header": str (optional), "dataType": str (optional) }
    expand: optional key into ROW_EXPAND to fan each hit into one row per nested
            array element (e.g. "external_attendees" → one row per attendee).
    """
    bindings = [c.get("binding", c) if isinstance(c, dict) else c for c in columns]
    paths = field_paths or REPORT_FIELD_PATHS
    expand_cfg = ROW_EXPAND.get(expand) if expand else None
    rows = []
    selected_hits = hits[:max_rows] if max_rows is not None else hits
    for h in selected_hits:
        source = h.get("source", h.get("_source", {}))
        if expand_cfg:
            rows.extend(_expand_hit_to_rows(source, bindings, expand_cfg, paths))
        else:
            rows.append(flatten_source_to_row(source, bindings, paths))
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
    expand=None,
):
    """
    Run an OpenSearch DSL query, flatten hits to rows, and return reportUiConfig + reportData.
    Use from the generate_report tool so the LLM does not send large payloads.

    group_by: optional list of column bindings to group rows by (e.g. ["region"]).
    sort_by: optional list of {"binding": str, "direction": "asc"|"desc"} for grid sorting.
    expand: optional ROW_EXPAND key to fan each event into one row per nested array
            element (e.g. "external_attendees" for an attendee-level report).
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
    rows = build_report_rows(hits, columns, max_rows=max_rows, expand=expand)
    return format_report(
        rows,
        columns,
        title=title,
        subtitle=subtitle,
        group_descriptions=_build_group_descriptions(group_by),
        sort_descriptions=_build_sort_descriptions(sort_by),
    )
