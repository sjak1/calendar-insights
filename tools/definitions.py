"""
Tool definitions for OpenAI function calling.
"""

tools = [
    {
        "type": "function",
        "name": "schedule_meeting",
        "description": "Create blocked calendar time using BriefingIQ API with ISO-8601 fields.",
        "parameters": {
            "type": "object",
            "properties": {
                "calendarFromDateIso": {
                    "type": "string",
                    "description": "Start date ISO string, e.g. 2025-10-28T00:00:00",
                },
                "calendarStartTimeIso": {
                    "type": "string",
                    "description": "Start time ISO string, e.g. 2025-10-28T01:00:00",
                },
                "calendarEndTimeIso": {
                    "type": "string",
                    "description": "End time ISO string, e.g. 2025-10-29T02:30:00",
                },
                "calendarToDateIso": {
                    "type": "string",
                    "description": "End date ISO string, e.g. 2025-10-30T00:00:00",
                },
                "calendarType": {
                    "type": "string",
                    "description": "Calendar type such as BLOCKED",
                },
                "comments": {
                    "type": ["string", "null"],
                    "description": "Optional comments",
                },
            },
            "required": [
                "calendarFromDateIso",
                "calendarStartTimeIso",
                "calendarEndTimeIso",
                "calendarToDateIso",
            ],
        },
    },
    # NOTE: Oracle query_database tool temporarily disabled — routing all queries through OpenSearch.
    # {
    #     "type": "function",
    #     "name": "query_database",
    #     "description": (
    #         "Query Oracle DB for structured operational data: events, meetings, attendees, opportunity/pipeline metrics, revenue. "
    #         "Use for: 'meetings this week', 'attendees for X', 'revenue by region', 'how many events', counts, dates, company/event lists. "
    #         "Do NOT use for free-text search over documents or content — use search_opensearch for that."
    #     ),
    #     "parameters": {
    #         "type": "object",
    #         "properties": {
    #             "question": {
    #                 "type": "string",
    #                 "description": "Natural language question to answer using the SQLite data.",
    #             }
    #         },
    #         "required": ["question"],
    #     },
    # },
    {
        "type": "function",
        "name": "format_chart",
        "description": (
            "Format data as a Highcharts configuration for visualization. "
            "Call AFTER search_opensearch returns aggs or _source data. "
            "Chart types: bar/column=categories (stacking for stacked), line/spline=trends, pie=parts of whole, "
            "area/areaspline=cumulative, heatmap=events by day×hour (use heatmap_data, x_axis_data, y_axis_data), "
            "xrange=event timeline/schedule (use xrange_data with [{x, x2, name}] Unix ms). Frontend renders the chart."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "chart_type": {
                    "type": "string",
                    "enum": [
                        "bar",
                        "column",
                        "line",
                        "pie",
                        "area",
                        "spline",
                        "areaspline",
                        "heatmap",
                        "xrange",
                    ],
                    "description": "bar/column/line/pie/area/spline/areaspline use x_axis_data+series_data. heatmap uses heatmap_data+x_axis_data+y_axis_data. xrange uses xrange_data.",
                },
                "title": {"type": "string", "description": "Chart title"},
                "x_axis_data": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Labels for x-axis (categories). For heatmap: column labels (e.g. days).",
                },
                "series_data": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "data": {"type": "array", "items": {"type": "number"}},
                        },
                    },
                    "description": "Data series [{name, data}]. Not used for heatmap/xrange.",
                },
                "y_axis_title": {
                    "type": "string",
                    "description": "Y-axis label (optional)",
                },
                "stacking": {
                    "type": "string",
                    "enum": ["normal", "percent"],
                    "description": "For bar/column: stacked bars. Omit for side-by-side.",
                },
                "subtitle": {
                    "type": "string",
                    "description": "Optional subtitle (e.g. date range)",
                },
                "heatmap_data": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "description": "For heatmap: [[xIndex, yIndex, value], ...] where indices refer to x_axis_data, y_axis_data",
                },
                "y_axis_data": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "For heatmap: row labels (e.g. hours 9am-5pm, or day names)",
                },
                "xrange_data": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "x": {
                                "type": "number",
                                "description": "Start time Unix ms",
                            },
                            "x2": {"type": "number", "description": "End time Unix ms"},
                            "name": {"type": "string"},
                            "y": {
                                "type": "number",
                                "description": "Row index (optional, default 0)",
                            },
                        },
                        "required": ["x", "x2", "name"],
                    },
                    "description": "For xrange: [{x: startMs, x2: endMs, name: 'Event'}] event timeline",
                },
                "xrange_categories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "For xrange: row labels when using multiple rows (y values)",
                },
            },
            "required": ["chart_type", "title"],
        },
    },
    {
        "type": "function",
        "name": "generate_agenda",
        "description": (
            "Generate an EBC agenda. Use ONLY when user explicitly asks to generate/create an agenda. "
            "If event_id in context, use it. If only company name (e.g. 'agenda for Jaguar'), use company_name. Do not invent event_id."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "Event ID to generate agenda for (optional if company_name provided)",
                },
                "company_name": {
                    "type": "string",
                    "description": "Company name to find meeting and generate agenda for (optional if event_id provided)",
                },
            },
            "required": [],
        },
    },
    {
        "type": "function",
        "name": "suggest_presenters",
        "description": (
            "Suggest the best presenters for a topic, event, industry, or customer. "
            "Use when the user asks who should present, who is the best presenter for X, or to recommend presenters for an agenda/session. "
            "Returns presenters ranked by matched activities, based on real activity-level topic/presenter matches. "
            "Provide at least one scope filter: event_id, topic, industry, or customer_name."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "Optional event ID to suggest presenters from this event's activities.",
                },
                "topic": {
                    "type": "string",
                    "description": "Optional topic name to find presenters who have presented on this topic.",
                },
                "industry": {
                    "type": "string",
                    "description": "Optional customer industry to match (e.g. Technology, Healthcare).",
                },
                "customer_name": {
                    "type": "string",
                    "description": "Optional customer/company name to match.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max number of presenters to return (default 10, max 50).",
                },
            },
            "required": [],
        },
    },
    {
        "type": "function",
        "name": "search_opensearch",
        "description": (
            "Use for lookups, lists, charts (aggs or _source), attendee questions. NOT for 'how many' — use count_opensearch. "
            "INDEX SELECTION: For event-level questions (attendees, opportunities, status, location, category) use default events index. "
            "For activity-level questions (topics, presenters, rooms, catering per session, per-activity scheduling) use index: 'activities'. "
            "For charts: call search_opensearch with aggs (terms on status/category/region) or size+_source, then format_chart. "
            "Filters/sort: use .keyword. _source: paths WITHOUT .keyword. startTime is epoch ms (events) or startTime.utcMs (activities). "
            "IMPORTANT: For keyword fields use field.keyword, for text fields with keyword subfield use field.keyword for exact match. "
            "For date range queries, MUST include format parameter (e.g. format: 'strict_date_optional_time||epoch_millis')."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "dsl_query": {
                    "type": "object",
                    "description": (
                        "OpenSearch request body: query, size, _source, sort, optional aggregations. "
                        "Example: {'query': {'bool': {'filter': [{'term': {'status.stateName.keyword': 'Initialized'}}]}}, 'size': 10, '_source': ['eventName', 'customerName'], 'sort': [{'startTime': {'order': 'asc'}}]}"
                    ),
                },
                "index": {
                    "type": "string",
                    "description": "Index name: 'events' (default) for event-level data, 'activities' for per-activity/topic/presenter data. Omit for events.",
                },
            },
            "required": ["dsl_query"],
        },
    },
    {
        "type": "function",
        "name": "count_opensearch",
        "description": (
            "Count documents matching a query in OpenSearch. "
            "Use when the user asks 'how many', 'count', 'number of', etc. "
            "Provide a query body (same as search query) and optional index. "
            "For activity-level counts (sessions, topics, presenters), use index: 'activities'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "object",
                    "description": 'The OpenSearch query object only (e.g. {"bool": {"filter": [...]}}). Do NOT wrap in an extra "query" key — the handler adds it. Same query shape as search_opensearch\'s query clause.',
                },
                "index": {
                    "type": "string",
                    "description": "Index name. Omit to use default index.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "type": "function",
        "name": "get_time_context",
        "description": (
            "Get the current time and compute epoch-ms day boundaries for a given date. "
            "Use this when you must answer 'today/tomorrow/next few days' questions and need the correct current date/time, timezone, "
            "or need start/end-of-day epoch milliseconds for filtering startTime (epoch ms). "
            "For multiple consecutive days (e.g. 'next 4 days'), prefer calling this ONCE with days_ahead instead of issuing multiple tool calls."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "date_iso": {
                    "type": "string",
                    "description": (
                        "Optional date to compute day boundaries for, in ISO format YYYY-MM-DD. "
                        "If omitted, uses today's date in the resolved timezone."
                    ),
                },
                "days_ahead": {
                    "type": "integer",
                    "description": (
                        "Optional number of consecutive days (including the base date) to compute. "
                        "For example, days_ahead=4 with date_iso='2026-03-17' returns ranges for 17th–20th. "
                        "If omitted or 1, only a single day is returned."
                    ),
                },
                "timezone": {
                    "type": "string",
                    "description": (
                        "IANA timezone name (e.g. America/Los_Angeles). "
                        "If omitted, uses request/context timezone from headers (fallback America/Los_Angeles)."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "type": "function",
        "name": "list_indices",
        "description": (
            "List OpenSearch indices. Use when the user asks what indices exist, how many indices, or index stats (docs.count, store.size). "
            "Optionally filter by index pattern (e.g. events*)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "index": {
                    "type": "string",
                    "description": "Index name or pattern (e.g. events*). Omit to list all indices.",
                },
                "include_detail": {
                    "type": "boolean",
                    "description": "If true (default), return full metadata (health, docs.count, store.size). If false, return only index names.",
                },
            },
            "required": [],
        },
    },
    {
        "type": "function",
        "name": "generate_pdf",
        "description": (
            "Generate a PDF document from text content for the user to download. "
            "Use when the user explicitly asks for PDF, export as PDF, download PDF, or save as PDF. "
            "Pass the full formatted text (report summary, agenda, analysis) as content. Title appears at top."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The full text content to include in the PDF (sections, bullets, paragraphs).",
                },
                "title": {
                    "type": "string",
                    "description": "Document title (e.g. 'Event Report', 'Agenda Summary'). Default: 'Document'.",
                },
            },
            "required": ["content"],
        },
    },
    {
        "type": "function",
        "name": "generate_report",
        "description": (
            "Generate a table report from OpenSearch. Use ONLY for explicit table/report/grid requests or specific columns. "
            "For 'list them' / 'show them' use search_opensearch. Columns: 4-6, bindings from schema (customer_name, event_name, status, location_name, event_start_time). "
            "_source: use paths WITHOUT .keyword (e.g. eventName, eventData.VISIT_INFO.data.customerName). Filters/sort: use .keyword. Frontend renders the table."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "dsl_query": {
                    "type": "object",
                    "description": "OpenSearch request body: query, size, _source, sort. For _source use stored paths WITHOUT .keyword (e.g. eventName, eventData.VISIT_INFO.data.customerName). For filters/sort use schema paths with .keyword.",
                },
                "columns": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "binding": {
                                "type": "string",
                                "description": "Field alias from schema. Common event aliases: event_name, customer_name, status, category_name, location_name, event_start_time, region, customer_industry, line_of_business, opportunity_revenue. Common activity aliases: presenter_name, topic_name, resource_name, start_time.",
                            },
                            "header": {
                                "type": "string",
                                "description": "Display label for column (optional).",
                            },
                        },
                    },
                    "description": "Columns to show in the table; binding must match schema aliases. Pick the minimum useful set for the question.",
                },
                "title": {"type": "string", "description": "Report title."},
                "subtitle": {
                    "type": "string",
                    "description": "Optional subtitle or time range label.",
                },
                "index": {
                    "type": "string",
                    "description": "OpenSearch index. Omit for default.",
                },
            },
            "required": ["dsl_query", "columns", "title"],
        },
    },
]
