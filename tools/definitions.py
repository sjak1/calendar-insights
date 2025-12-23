"""
Tool definitions for OpenAI function calling.
"""

tools = [
    {
        "type": "function",
        "name": "get_gdp",
        "description": "get a countries gdp for a particular year",
        "parameters": {
            "type": "object",
            "properties": {
                "country": {
                    "type": "string",
                    "description": "country in the world map",
                },
                "year": {
                    "type": "string",
                    "description": "a valid calender year",
                },
            },
            "required": ["country", "year"],
        },
    },
    {
        "type": "function",
        "name": "schedule_meeting",
        "description": "Create blocked calendar time using BriefingIQ API with ISO-8601 fields.",
        "parameters": {
            "type": "object",
            "properties": {
                "calendarFromDateIso": {
                    "type": "string",
                    "description": "Start date ISO string, e.g. 2025-10-28T00:00:00"
                },
                "calendarStartTimeIso": {
                    "type": "string",
                    "description": "Start time ISO string, e.g. 2025-10-28T01:00:00"
                },
                "calendarEndTimeIso": {
                    "type": "string",
                    "description": "End time ISO string, e.g. 2025-10-29T02:30:00"
                },
                "calendarToDateIso": {
                    "type": "string",
                    "description": "End date ISO string, e.g. 2025-10-30T00:00:00"
                },
                "calendarType": {
                    "type": "string",
                    "description": "Calendar type such as BLOCKED"
                },
                "comments": {
                    "type": ["string", "null"],
                    "description": "Optional comments"
                }
            },
            "required": [
                "calendarFromDateIso",
                "calendarStartTimeIso",
                "calendarEndTimeIso",
                "calendarToDateIso"
            ]
        }
    },
    {
        "type": "function",
        "name": "query_database",
        "description": (
            "Use this when the user asks about meeting operations, attendees, or opportunity metrics. "
            "It queries oracle db"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Natural language question to answer using the SQLite data."
                }
            },
            "required": ["question"]
        }
    },
    {
        "type": "function",
        "name": "format_chart",
        "description": (
            "Format data as a Highcharts configuration for visualization. "
            "Use when user asks for charts, graphs, bar charts, pie charts, or visual representations of data. "
            "Call this AFTER getting data from query_database if user wants visualization."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "chart_type": {
                    "type": "string",
                    "enum": ["bar", "column", "line", "pie", "area"],
                    "description": "Type of chart to generate"
                },
                "title": {
                    "type": "string",
                    "description": "Chart title"
                },
                "x_axis_data": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Labels for x-axis (categories)"
                },
                "series_data": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "data": {"type": "array", "items": {"type": "number"}}
                        }
                    },
                    "description": "Data series for the chart"
                },
                "y_axis_title": {
                    "type": "string",
                    "description": "Y-axis label (optional)"
                }
            },
            "required": ["chart_type", "title", "x_axis_data", "series_data"]
        }
    },
    {
        "type": "function",
        "name": "generate_agenda",
        "description": (
            "Generate a sample EBC (Executive Briefing Center) agenda for an engagement request. "
            "Use when user asks to generate an agenda, create a briefing schedule, or requests an EBC agenda. "
            "Fetches company profile, attendees, sales plays, and similar meetings to create a tailored agenda."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "Event ID to generate agenda for (optional if company_name provided)"
                },
                "company_name": {
                    "type": "string",
                    "description": "Company name to find meeting and generate agenda for (optional if event_id provided)"
                }
            },
            "required": []
        }
    },
]
