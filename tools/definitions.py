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
            "Also call it PROACTIVELY when preparing a briefing — after research_company, for the topics that research surfaced — so the draft carries presenter suggestions instead of leaving them for later. "
            "Returns presenters ranked by matched activities, based on real activity-level topic/presenter matches. "
            "Provide at least one scope filter: event_id, topic, industry, or customer_name. "
            "Topic matching is lexical, so a topic the tenant has no wording for returns no one. "
            "When that happens the response carries available_topics — the topics that DO exist. "
            "Pick the closest genuinely related one and tell the user which you substituted and why, "
            "or report that nobody has presented on what they asked for. Never retry with vaguer "
            "wording until something returns and then present those people as experts in the "
            "original topic — describe presenters by the topic they actually matched. "
            "Set audience_level when the briefing has senior attendees — presenters will be ranked so peers of the audience surface first. "
            "Set check_start_utc_ms + check_end_utc_ms (epoch ms) to get availability — each result will include available:true/false and any conflict details. "
            "Use time placeholder tokens (TODAY_START etc.) or ISO date strings — the server converts to epoch_ms."
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
                "check_start_utc_ms": {
                    "type": "integer",
                    "description": (
                        "Session start time as epoch milliseconds (UTC). When provided together with check_end_utc_ms, "
                        "each suggested presenter will include available:true/false and conflict details. "
                        "Use time placeholder token strings (e.g. TODAY_START) or ISO date strings — server converts automatically."
                    ),
                },
                "check_end_utc_ms": {
                    "type": "integer",
                    "description": "Session end time as epoch milliseconds (UTC). Must be paired with check_start_utc_ms.",
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
            "For date range queries on epoch_millis fields, write placeholder TOKENS (TODAY_START, THIS_MONTH_END, etc.) "
            "or ISO date strings ('YYYY-MM-DD'). The server substitutes them for real epoch_ms before executing — "
            "see [Time Context] in the system prompt for the full token list. ALWAYS include format: 'epoch_millis'."
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
            "For 'list them' / 'show them' use search_opensearch. "
            "COLUMNS: default to the FULL relevant set for the entity (typically 8-12), not a minimal one — users expect complete grids and can hide columns in the UI. "
            "Event reports: event_name, customer_name, status, category_name, location_name, event_start_time, region, customer_industry, line_of_business, opportunity_revenue. "
            "Attendee reports (expand set): attendee_type, attendee_name, attendee_title, attendee_email, attendee_company, chief_officer_title, is_remote, decision_maker, is_technical. "
            "Only narrow the columns when the user explicitly names the fields they want. "
            "_source: use paths WITHOUT .keyword (e.g. eventName, eventFormData.VISIT_INFO.customerName) and include every path the columns need. Filters/sort: use .keyword. Frontend renders the table."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "dsl_query": {
                    "type": "object",
                    "description": "OpenSearch request body: query, size, _source, sort. For _source use stored paths WITHOUT .keyword (e.g. eventName, eventFormData.VISIT_INFO.customerName). For filters/sort use schema paths with .keyword.",
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
                    "description": "Columns to show in the table; binding must match schema aliases. Default to the full relevant set for the entity (8-12 columns); only narrow when the user names specific fields.",
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
                "group_by": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of column bindings to group rows by in the grid (e.g. [\"region\"] or [\"status\"]). Use when the user asks to group/break down the report by a field.",
                },
                "sort_by": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "binding": {"type": "string", "description": "Column binding to sort on."},
                            "direction": {"type": "string", "enum": ["asc", "desc"], "description": "Sort direction. Default asc."},
                        },
                    },
                    "description": "Optional grid sort order, e.g. [{\"binding\": \"opportunity_revenue\", \"direction\": \"desc\"}].",
                },
                "expand": {
                    "type": "string",
                    "enum": ["all_attendees", "external_attendees", "internal_attendees"],
                    "description": "Optional. Fan each event into one row per nested attendee for an attendee-level report. Prefer 'all_attendees' (internal + external combined, with an attendee_type column of Internal/External) unless the user asks for only one type. Use item-level column bindings like attendee_type, attendee_name, attendee_title, attendee_email, attendee_company, chief_officer_title, is_remote, decision_maker. To mirror the native contact grid, also pass group_by: [\"event_id_top\", \"attendee_type\"]. When expanding, include the attendee arrays in _source (eventFormData.INTERNAL_ATTENDEES and/or eventFormData.EXTERNAL_ATTENDEES). Omit for a normal one-row-per-event report.",
                },
            },
            "required": ["dsl_query", "columns", "title"],
        },
    },
    {
        "type": "function",
        "name": "draft_confirmation_email",
        "description": (
            "Draft a professional event confirmation email to send to the customer. "
            "Fetches live event details (date, location, agenda, host) and returns a ready-to-send subject + body. "
            "Use when the user asks to 'draft a confirmation', 'send a confirmation email', or 'confirm the event with the customer'. "
            "event_id defaults to the one in the request header context if not passed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "Event UUID. Defaults to header context.",
                },
                "host_name": {
                    "type": "string",
                    "description": "Override the host name in the email signature.",
                },
                "host_email": {
                    "type": "string",
                    "description": "Override the host email in the email signature.",
                },
                "additional_notes": {
                    "type": "string",
                    "description": "Any extra instructions or notes to include in the email body.",
                },
            },
            "required": [],
        },
    },
    {
        "type": "function",
        "name": "draft_catering_sheet",
        "description": (
            "Draft an internal ops/catering and room-setup sheet for the EBC team. "
            "Groups sessions by room and lists catering and AV requirements inferred from activity types. "
            "Use when the user asks for a 'catering sheet', 'setup sheet', 'ops sheet', or 'room requirements'. "
            "event_id defaults to the one in the request header context if not passed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "Event UUID. Defaults to header context.",
                },
                "include_av": {
                    "type": "boolean",
                    "description": "Include AV/tech setup notes per session. Default true.",
                },
            },
            "required": [],
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
    {
        "type": "function",
        "name": "research_company",
        "description": (
            "Gather public background on a customer ahead of a briefing — profile, recent news, "
            "and strategic priorities — to inform the objective, agenda topics, and presenter "
            "choices. "
            "CALL THIS PROACTIVELY, without being asked, BEFORE draft_briefing whenever you are "
            "preparing a briefing for a customer you have not already researched in this "
            "conversation — the findings are what make the objective and agenda specific to that "
            "customer rather than generic. Also use it when advising on an existing briefing. "
            "Do NOT call it as a general web search: if the user asks about a company with no "
            "briefing in view, or wants a definition or unrelated lookup, answer from your own "
            "knowledge instead. "
            "READ-ONLY: writes nothing to BriefingIQ. Present the findings WITH their source "
            "links and let the user confirm before any of it informs a briefing record. "
            "If the company name is ambiguous (a common word, or several companies share it), "
            "ask the user which entity they mean first."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "company_name": {"type": "string", "description": "Customer/company to research."},
                "focus": {
                    "type": "string",
                    "description": "Optional extra angle, e.g. 'cloud migration' or 'supply chain'.",
                },
            },
            "required": ["company_name"],
        },
    },
    {
        "type": "function",
        "name": "search_briefingiq_endpoints",
        "description": (
            "Search the catalog of 200+ read-only BriefingIQ API endpoints (locations, location hours, "
            "presenters, presenter calendars, meetings, meeting history, attendees, topics, resources, "
            "vacant time slots, roles, reports, forms, notes, ...). Use this when no dedicated tool covers "
            "the user's question but live BriefingIQ data might — then pass the chosen endpoint id to "
            "call_briefingiq_endpoint. Returns: [{id, path, tag, summary, params}]."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keywords describing the data needed, e.g. 'presenter calendar' or 'location hours'.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "type": "function",
        "name": "call_briefingiq_endpoint",
        "description": (
            "Execute a read-only (GET) BriefingIQ API endpoint found via search_briefingiq_endpoints. "
            "Fill every {placeholder} in the endpoint path via path_params (event ids default to the "
            "current event from context). Auth is forwarded from the user's session, so results respect "
            "their permissions. Returns the endpoint's JSON response (large lists are truncated)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "endpoint_id": {
                    "type": "string",
                    "description": "Endpoint id from search_briefingiq_endpoints, e.g. 'get_roledataaccess'.",
                },
                "path_params": {
                    "type": "object",
                    "description": "Values for {placeholders} in the path, e.g. {\"eventid\": \"<uuid>\"}.",
                },
                "query_params": {
                    "type": "object",
                    "description": "Query-string parameters listed in the endpoint's params.",
                },
            },
            "required": ["endpoint_id"],
        },
    },
    {
        "type": "function",
        "name": "draft_briefing",
        "description": (
            "Assemble a complete NEW briefing request draft for user review — NO writes happen. "
            "Use after interviewing the user. Unless you have already done so in this "
            "conversation, call research_company FIRST and fold what you learn into the "
            "objective and agenda, then call suggest_presenters for the topics that research "
            "surfaced — research tells you which topics matter, and those topics are what "
            "presenter matching needs. Show the user the research and the suggested presenters "
            "alongside the draft. Do not repeat research you have already run this conversation. "
            "Required: customer name, primary opportunity id, date, "
            "start/end time. Optional: objective, duration in days (1-5), presenters and agenda sessions "
            "(pushed after creation), attendees (recorded, not yet auto-pushed). "
            "Returns a draft_id + a markdown summary. ALWAYS show the summary (and any assumptions) to the "
            "user and wait for their explicit confirmation before calling push_briefing."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "customer_name": {"type": "string", "description": "Customer/account the briefing is for."},
                "opportunity_id": {"type": "string", "description": "Primary opportunity ID (required by the request form). Ask the user for it."},
                "objective": {
                    "type": "string",
                    "description": (
                        "Briefing objective / purpose. Stored on the briefing (max 200 chars, "
                        "truncated beyond that) — write it for the customer, not the host."
                    ),
                },
                "region": {
                    "type": "string",
                    "description": "Customer region, e.g. North America, EMEA, JAPAC.",
                },
                "company_website": {
                    "type": "string",
                    "description": "Customer website. Use research_company findings; confirm with the user first.",
                },
                "company_industry": {
                    "type": "string",
                    "description": "Customer industry. Use research_company findings; confirm with the user first.",
                },
                "company_country": {
                    "type": "string",
                    "description": "Customer country. Use research_company findings; confirm with the user first.",
                },
                "briefing_date": {"type": "string", "description": "YYYY-MM-DD."},
                "start_time": {"type": "string", "description": "HH:MM 24-hour, in the request timezone."},
                "end_time": {"type": "string", "description": "HH:MM 24-hour."},
                "duration_days": {"type": "integer", "description": "Briefing length in days, 1-5. Default 1."},
                "room_name": {"type": "string", "description": "Optional room preference (noted; booked separately after creation)."},
                "presenter_emails": {"type": "array", "items": {"type": "string"}},
                "internal_attendees": {"type": "array", "items": {"type": "object"}},
                "external_attendees": {"type": "array", "items": {"type": "object"}},
                "agenda_sessions": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Optional [{title, time_slot}] sessions from generate_agenda to push as agenda.",
                },
            },
            "required": ["customer_name", "opportunity_id", "briefing_date", "start_time", "end_time"],
        },
    },
    {
        "type": "function",
        "name": "get_briefing",
        "description": (
            "Read an EXISTING briefing's current field values, status, and the state actions available "
            "from that status. Call this BEFORE any edit so you can show the user current vs proposed "
            "values, and to discover valid actions for change_briefing_state. "
            "Find the request_id first (e.g. call_briefingiq_endpoint get_events, or the id returned by "
            "push_briefing). Returns: {event_number, status, fields, available_actions, editable_fields}."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "Briefing (CBR event / request) UUID."},
            },
            "required": ["request_id"],
        },
    },
    {
        "type": "function",
        "name": "reschedule_briefing",
        "description": (
            "Move an EXISTING briefing to a new date/time. Works on any briefing — AI-created or made "
            "by hand in the app. Call get_briefing first, show the user current vs proposed schedule, "
            "and call this ONLY after they explicitly confirm. Room changes are NOT applied here."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "Briefing (CBR event / request) UUID."},
                "new_date": {"type": "string", "description": "YYYY-MM-DD."},
                "start_time": {"type": "string", "description": "HH:MM 24-hour."},
                "end_time": {"type": "string", "description": "HH:MM 24-hour."},
                "duration_days": {"type": "integer", "description": "Optional new length in days, 1-5."},
            },
            "required": ["request_id", "new_date", "start_time", "end_time"],
        },
    },
    {
        "type": "function",
        "name": "update_briefing_details",
        "description": (
            "Update fields on an EXISTING briefing. Read-modify-write: only the keys you pass change, "
            "everything else is preserved. Field names come from get_briefing's editable_fields — "
            "typically customerName, primaryOpportunity, secondaryOpportunity, region, tier, "
            "briefingManager, accountId, duration. Show the user current -> proposed values and get "
            "explicit confirmation before calling."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "Briefing (CBR event / request) UUID."},
                "changes": {"type": "object", "description": "Map of field name to new value."},
            },
            "required": ["request_id", "changes"],
        },
    },
    {
        "type": "function",
        "name": "change_briefing_state",
        "description": (
            "Move an EXISTING briefing through its workflow: SUBMIT, CONFIRM, HOLD, WAITLIST, CANCEL, "
            "DECLINE, etc. Valid actions depend on current status — call get_briefing first and use its "
            "available_actions. Get explicit user confirmation before calling, and warn them when the "
            "action is terminal (CANCEL/DECLINE). Notification emails are OFF unless send_notification "
            "is true — only set it if the user explicitly asks to notify people, since it emails real customers."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "Briefing (CBR event / request) UUID."},
                "action": {"type": "string", "description": "Action name from get_briefing's available_actions."},
                "send_notification": {"type": "boolean", "description": "Email participants. Default false."},
            },
            "required": ["request_id", "action"],
        },
    },
    {
        "type": "function",
        "name": "push_briefing",
        "description": (
            "Execute the writes for a confirmed briefing draft: creates the briefing request via the "
            "forms engine (a new CBR event), SUBMITs it (no notification emails), and optionally pushes "
            "agenda sessions. Call ONLY after the user explicitly confirmed the draft summary from "
            "draft_briefing — never on your own initiative. A draft can be pushed at most once. "
            "Returns the new request_id + CBR event number and per-step success/failure."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string", "description": "draft_id returned by draft_briefing."},
            },
            "required": ["draft_id"],
        },
    },
]
