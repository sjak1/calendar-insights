"""
Tool definitions for OpenAI function calling.
"""

tools = [
    {
        "type": "function",
        "name": "list_rooms",
        "description": (
            "List bookable rooms. If an event_id is available (from context header or arg), returns "
            "event-level rooms (e.g. Horizon Chamber, Panorama Suite) — these are the rooms on that event's calendar. "
            "If no event context, returns tenant-wide rooms (Outlook 1-6, Executive Lounge). "
            "Call this FIRST when the user asks about rooms, availability, or wants to book. "
            "Returns: [{resource_id, name, source, dates?}]."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "Optional event UUID. If omitted, uses event_id from request header context (if any).",
                },
            },
            "required": [],
        },
    },
    {
        "type": "function",
        "name": "list_event_activities",
        "description": (
            "List every scheduled activity on an event — sessions, catering, topics — across all rooms. "
            "Use when the user asks 'what activities do I have today?', 'what's on the agenda?', or similar. "
            "Pass a date (YYYY-MM-DD) to narrow to one day; omit for the whole event. "
            "event_id defaults to the one in the request header context if not passed. "
            "Returns: [{activity_id, title, activity_type, start_iso, end_iso, date, room_name, room_id, status}]."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "Optional event UUID. Defaults to header context.",
                },
                "date": {
                    "type": "string",
                    "description": "Optional YYYY-MM-DD to filter activities to a single day.",
                },
            },
            "required": [],
        },
    },
    {
        "type": "function",
        "name": "get_resource_schedule",
        "description": (
            "Fetch existing calendar entries (bookings/blocks) for a specific room. "
            "Use to show the user what's already booked on a room, or to decide when to schedule."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "resource_id": {
                    "type": "string",
                    "description": "Room resource UUID from list_rooms.",
                },
            },
            "required": ["resource_id"],
        },
    },
    {
        "type": "function",
        "name": "find_vacant_slots",
        "description": (
            "Find free time windows of a given minimum duration on a specific date for a room. "
            "Use this for natural-language booking requests like 'find a 1-hour slot tomorrow' or "
            "'when is Outlook3 free on Friday'. Respects working hours (default 9am–6pm in the request timezone)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "resource_id": {
                    "type": "string",
                    "description": "Room resource UUID from list_rooms.",
                },
                "date": {
                    "type": "string",
                    "description": "Target date in YYYY-MM-DD.",
                },
                "duration_minutes": {
                    "type": "integer",
                    "description": "Minimum slot length required, in minutes.",
                },
                "day_start_hour": {
                    "type": "integer",
                    "description": "Working-day start hour (24h). Default 9.",
                },
                "day_end_hour": {
                    "type": "integer",
                    "description": "Working-day end hour (24h). Default 18.",
                },
            },
            "required": ["resource_id", "date", "duration_minutes"],
        },
    },
    {
        "type": "function",
        "name": "block_calendar",
        "description": (
            "Reserve a time window on a room by creating a calendar entry (default type BLOCKED). "
            "Runs a conflict check first — if the window overlaps any existing entry, returns "
            "status='conflict' with the conflicting entries instead of writing. "
            "Call list_rooms (and optionally find_vacant_slots) before this."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "resource_id": {
                    "type": "string",
                    "description": "Room resource UUID from list_rooms.",
                },
                "start_iso": {
                    "type": "string",
                    "description": "Local wall-clock start in ISO-8601 'YYYY-MM-DDTHH:MM:SS'.",
                },
                "end_iso": {
                    "type": "string",
                    "description": "Local wall-clock end in ISO-8601 'YYYY-MM-DDTHH:MM:SS'.",
                },
                "comments": {
                    "type": ["string", "null"],
                    "description": "Optional note stored on the entry (e.g. meeting purpose).",
                },
                "calendar_type": {
                    "type": "string",
                    "description": "Entry type. Default 'BLOCKED'.",
                },
            },
            "required": ["resource_id", "start_iso", "end_iso"],
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
            "Provide at least one scope filter: event_id, topic, industry, or customer_name. "
            "Set audience_level when the briefing has senior attendees — presenters will be ranked so peers of the audience surface first."
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
                "audience_level": {
                    "type": "string",
                    "enum": ["c_level", "vp_plus", "senior"],
                    "description": (
                        "Seniority of the briefing audience. 'c_level' = CEO/CFO/CTO etc, "
                        "'vp_plus' = VP/EVP/SVP, 'senior' = Director+. "
                        "When set, presenters with matching title tiers and past experience with that audience are ranked first."
                    ),
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
    # get_event_rooms merged into list_rooms — list_rooms now auto-detects event context
    # and returns event-level rooms when event_id is available.
    {
        "type": "function",
        "name": "push_agenda_to_briefingiq",
        "description": (
            "Push AI-generated agenda sessions into BriefingIQ as calendar activities. "
            "Use ONLY after generate_agenda has produced sessions AND the user explicitly confirms they want to add it to the event. "
            "Call list_rooms first to get available rooms. If multiple rooms exist, ask the user which one to use."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "BriefingIQ event UUID.",
                },
                "event_date": {
                    "type": "string",
                    "description": "Start date of the event in YYYY-MM-DD format.",
                },
                "sessions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Session title."},
                            "time_slot": {"type": "string", "description": "Time range e.g. '10:00 AM - 10:45 AM'."},
                        },
                        "required": ["title", "time_slot"],
                    },
                    "description": "List of agenda sessions from generate_agenda output.",
                },
                "resource_id": {
                    "type": "string",
                    "description": "Room resource UUID from get_event_rooms. Optional — if omitted, activities are created without room assignment.",
                },
                "presenter_emails": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of presenter email addresses to add to every session.",
                },
            },
            "required": ["event_id", "event_date", "sessions"],
        },
    },
]
