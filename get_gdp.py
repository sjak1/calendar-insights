import requests
from openai import OpenAI
import json
from dotenv import load_dotenv
from datetime import datetime, date
import uuid

from scripts.sqlite_qa import ask_sqlite
from logging_config import get_logger

load_dotenv()

client = OpenAI()
logger = get_logger(__name__)

# In-memory session storage: {session_id: [list of messages]}
# Each message is a dict with role and content
chat_sessions = {}


def json_dumps_safe(obj):
    """
    Safely serialize objects to JSON, converting datetime and date objects to ISO format strings.
    Handles datetime/date objects and other non-serializable types that may come from database queries.
    """
    def default_serializer(o):
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        # Try to use model_dump if it's a Pydantic model
        if hasattr(o, 'model_dump'):
            return o.model_dump()
        # Try to convert to dict if it has __dict__
        if hasattr(o, '__dict__'):
            return o.__dict__
        # Handle other non-serializable types
        return str(o)
    
    return json.dumps(obj, default=default_serializer)

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
    # commented out because it is not used
    #{
    #    "type": "function",
    #    "name": "get_calendars",
    #    "description": "Fetch schedules for the configured resource using BriefingIQ API (GET; no payload).",
    #    "parameters": {"type": "object", "properties": {}, "required": []},
    #},
    #{
     #   "type": "function",
      #  "name": "get_resources",
       # "description": "Fetch all resources of a specific resource type (e.g., Location, Presenter, Room) from BriefingIQ.",
       # "parameters": {
        #    "type": "object",
        #    "properties": {
        #        "resource_type_id": {
        #            "type": "string",
        #            "description": "The unique ID of the resource type. Common IDs: EEF43C5C-B5E6-41C6-9634-8D812AC43FC8 (Location), f57aea4f-dc69-475b-b02d-96259c216699 (Presenter), EAC8F953-99D0-43DF-8E15-CA03F21EA92D (Room)"
        #        }
        #    },
        #    "required": ["resource_type_id"]
        #}
    #},
    #{
    #    "type": "function",
    #    "name": "oracle_financial_stats",
    #    "description": "Get the financial stats of a company for a particular year",
    #    "parameters": {
    #        "type": "object",
    #        "properties": {
    #        "year": {
    #            "type": "string",
    #            "description": "a valid calender year"
    #        }
    #    },
    #    "required": ["year"]
    #}
    #{
    #    "type": "function",
    #    "name": "add_fruit",
    #    "description": "Add a fruit to the list",
    #    "parameters": {
    #        "type": "object",
    #        "properties": {
    #            "fruit": {"type": "string", "description": "the fruit to add"}
    #        },
    #        "required": ["fruit"]
    #    }
    #},
    #{
    #    "type": "function",
    #    "name": "get_report_data",
    #    "description": "Fetch admin report data for the configured tenant within an OPTIONAL date range. if no date range is provided leave it blank. lookupType can be used to scope the data.",
    #    "parameters": {
    #        "type": "object",
    #        "properties": {
    #            "fromDate": {
    #                "type": "string",
    #                "description": "ISO-8601 timestamp for the start filter, e.g. 2025-11-11T15:18:27",
    #            },
    #            "toDate": {
    #                "type": "string",
    #                "description": "ISO-8601 timestamp for the end filter, e.g. 2025-11-11T16:18:27",
    #            },
    #            "lookupType": {
    #                "type": "string",
    #                "description": (
    #                    "Optional lookup filter such as region, lineOfBusiness, customerIndustry, "
    #                    "visitFocus, visitType, or companyName"
    #                ),
    #            },
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
]

fruits = ["apple","banana","guava","mango"]
def get_fruits():
    return fruits

def add_fruit(fruit):
    fruits.append(fruit)
    return fruits

def oracle_financial_stats(year):
    if (year == "2024"):
        return {
           "profit": 1000000,
            "revenue": 2000000,
            "expenses": 1000000,
            "net_income": 1000000,
            "gross_profit": 1000000,
            "gross_margin": 0.5,
            "net_margin": 0.5,
            "return_on_assets": 0.5,
            "return_on_equity": 0.5,
        }
    elif (year == "2025"):
        return {
            "profit": 1500000,
            "revenue": 2500000,
            "expenses": 1500000,
            "net_income": 500000,
            "gross_profit": 1000000,
            "gross_margin": 0.5,
            "net_margin": 0.5,
            "return_on_assets": 0.5,
            "return_on_equity": 0.5,
        }

def get_horoscope(sign):
    return f"{sign}: next tuesday you will befriend a baby otter or a baby seal."

def get_gdp(country, year):

    url = "https://api.api-ninjas.com/v1/gdp"
    headers = {"X-Api-Key": "QxU+IiicXDXJonqyCUJGHw==1pyYpxF0JDK4LMPy"}

    params = {"country": country, "year": year}
    res = requests.get(url, headers=headers, params=params)
    if res.ok:
        return res.json()
    else:
        return ("error:", res.status_code, res.text) 

def schedule_meeting(
    calendarFromDateIso,
    calendarStartTimeIso,
    calendarEndTimeIso,
    calendarToDateIso,
    calendarType="BLOCKED",
    comments=None,
    headers=None,
):
    url = (
        "https://briefings.briefingiq.com/"
        "events/api/resources/26C5712B-4520-421A-B41D-08A030F62B37/calendars"
    )

    if headers is None or not headers:
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "x-cloud-customerid": "131393dd-0449-4cca-8528-2fed6b79eaed",
            "x-cloud-categoryid": "D06189A1-69AF-4D17-AC5B-480F7589D427",
            "x-cloud-categorytypeid": "CATEGORY_TYPE_BRIEFINGS",
            "x-cloud-client-timezone": "Asia/Calcutta",
            "x-cloud-context-timezone": "America/Los_Angeles",
            "x-cloud-requested-timezone": "America/Los_Angeles",
            "x-cloud-eventid": "389C0AA1-6BCD-4579-B410-D4A55219F7FB",
            "X_cloud_user": "surya.yadavalli@briefingiq.com",
            "authorization": (
                "Bearer "
                "eyJraWQiOiJRYTViRDR0aEc4aVpnLTV0WE04cmJOa3M5TEkxam40YnBXZmpHWWlVNlE0IiwiYWxnIjoiUlMyNTYifQ.eyJ2ZXIiOjEsImp0aSI6IkFULk5fbUpKTkZLR0dJbkdzbnFFWFRhSVRmdTF4ZVlVeUk4OERMdVhLcXdxLXcub2FyNDA1NzRqczdodW00WVk1ZDciLCJpc3MiOiJodHRwczovL2Rldi0zMDczNDMxMC5va3RhLmNvbS9vYXV0aDIvZGVmYXVsdCIsImF1ZCI6ImFwaTovL2RlZmF1bHQiLCJpYXQiOjE3NjI0MjA4MzgsImV4cCI6MTc2MjQyNDQzOCwiY2lkIjoiMG9hOHI4bWt1M05YdkFwMzM1ZDciLCJ1aWQiOiIwMHU4dHl4ZWdsNFFIV3B3TDVkNyIsInNjcCI6WyJwcm9maWxlIiwib2ZmbGluZV9hY2Nlc3MiLCJvcGVuaWQiXSwiYXV0aF90aW1lIjoxNzYyNDIwODM1LCJzdWIiOiJzdXJ5YS55YWRhdmFsbGlAYnJpZWZpbmdpcS5jb20ifQ.mqHvJHRQGuJwmwI_Lh7Kh7J-PJsytMsK8EpCWhPYUbZn15RfYkwz4yBm_uKeptjGk-3K-TuSwJtsbP-bP9veCCjVQXWL4yaZhcfLyD3mIkufVuDIPkEyklaXnaf-R2QWPJztxhQw59klKi-tCe18WhHLDE1UWOfI1jw2JY0mxiKMkEs1CKz6isfPWX72vVdYVWE458hUjTTv9mDhWsR4l8brMnPKMhCHlpcP7UDtCVNleaP9fR3-uaUvHgLwRVjfwalVMbrNXJfVRxwzx9SUhuC2QaaKO0fvnHjL8Lxp03uON-0mYYK75v_VnQTQzRiKvInuAb8vfFTBROlJZAPhVQ"
            ),
        }

    data = {
        "calendarFromDate": {"isoDate": calendarFromDateIso},
        "calendarStartTime": {"isoDate": calendarStartTimeIso},
        "calendarEndTime": {"isoDate": calendarEndTimeIso},
        "calendarType": calendarType,
        "comments": comments,
        "calendarToDate": {"isoDate": calendarToDateIso},
    }

    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    
    # API returns 200 with empty body
    if not response.text:
        return {"status": "success", "message": "Meeting scheduled successfully"}
    
    return {"status": response.status_code, "data": response.json()}


def get_calendars():
    url = (
        "https://briefings.briefingiq.com/"
        "events/api/resources/26C5712B-4520-421A-B41D-08A030F62B37/calendars"
    )

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "x-cloud-customerid": "131393dd-0449-4cca-8528-2fed6b79eaed",
        "X_cloud_user": "surya.yadavalli@briefingiq.com",
        "authorization": (
            "Bearer "
            "eyJraWQiOiJRYTViRDR0aEc4aVpnLTV0WE04cmJOa3M5TEkxam40YnBXZmpHWWlVNlE0IiwiYWxnIjoiUlMyNTYifQ.eyJ2ZXIiOjEsImp0aSI6IkFULk5mbUpKTkZLR0dJbkdzbnFFWFRhSVRmdTF4ZVlVeUk4OERMdVhLcXdxLXcub2FyNDA1NzRqczdodW00WVk1ZDciLCJpc3MiOiJodHRwczovL2Rldi0zMDczNDMxMC5va3RhLmNvbS9vYXV0aDIvZGVmYXVsdCIsImF1ZCI6ImFwaTovL2RlZmF1bHQiLCJpYXQiOjE3NjI0MjA4MzgsImV4cCI6MTc2MjQyNDQzOCwiY2lkIjoiMG9hOHI4bWt1M05YdkFwMzM1ZDciLCJ1aWQiOiIwMHU4dHl4ZWdsNFFIV3B3TDVkNyIsInNjcCI6WyJwcm9maWxlIiwib2ZmbGluZV9hY2Nlc3MiLCJvcGVuaWQiXSwiYXV0aF90aW1lIjoxNzYyNDIwODM1LCJzdWIiOiJzdXJ5YS55YWRhdmFsbGlAYnJpZWZpbmdpcS5jb20ifQ.mqHvJHRQGuJwmwI_Lh7Kh7J-PJsytMsK8EpCWhPYUbZn15RfYkwz4yBm_uKeptjGk-3K-TuSwJtsbP-bP9veCCjVQXWL4yaZhcfLyD3mIkufVuDIPkEyklaXnaf-R2QWPJztxhQw59klKi-tCe18WhHLDE1UWOfI1jw2JY0mxiKMkEs1CKz6isfPWX72vVdYVWE458hUjTTv9mDhWsR4l8brMnPKMhCHlpcP7UDtCVNleaP9fR3-uaUvHgLwRVjfwalVMbrNXJfVRxwzx9SUhuC2QaaKO0fvnHjL8Lxp03uON-0mYYK75v_VnQTQzRiKvInuAb8vfFTBROlJZAPhVQ"
        ),
    }

    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()


def get_resources(resource_type_id, headers=None):
    """
    Fetch all resources of a specific resource type from BriefingIQ.
    
    Args:
        resource_type_id: The unique ID of the resource type
        headers: Optional custom headers (if None, uses default headers)
    
    Returns:
        JSON response containing the resources
    """
    url = (
        f"https://briefings.briefingiq.com/"
        f"events/api/resourcetypes/{resource_type_id}/resources"
    )

    if headers is None or not headers:
        headers = {
            "accept": "application/json, text/plain, */*",
            "authorization": (
                "Bearer "
                "eyJraWQiOiJRYTViRDR0aEc4aVpnLTV0WE04cmJOa3M5TEkxam40YnBXZmpHWWlVNlE0IiwiYWxnIjoiUlMyNTYifQ.eyJ2ZXIiOjEsImp0aSI6IkFULk5fbUpKTkZLR0dJbkdzbnFFWFRhSVRmdTF4ZVlVeUk4OERMdVhLcXdxLXcub2FyNDA1NzRqczdodW00WVk1ZDciLCJpc3MiOiJodHRwczovL2Rldi0zMDczNDMxMC5va3RhLmNvbS9vYXV0aDIvZGVmYXVsdCIsImF1ZCI6ImFwaTovL2RlZmF1bHQiLCJpYXQiOjE3NjI0MjA4MzgsImV4cCI6MTc2MjQyNDQzOCwiY2lkIjoiMG9hOHI4bWt1M05YdkFwMzM1ZDciLCJ1aWQiOiIwMHU4dHl4ZWdsNFFIV3B3TDVkNyIsInNjcCI6WyJwcm9maWxlIiwib2ZmbGluZV9hY2Nlc3MiLCJvcGVuaWQiXSwiYXV0aF90aW1lIjoxNzYyNDIwODM1LCJzdWIiOiJzdXJ5YS55YWRhdmFsbGlAYnJpZWZpbmdpcS5jb20ifQ.mqHvJHRQGuJwmwI_Lh7Kh7J-PJsytMsK8EpCWhPYUbZn15RfYkwz4yBm_uKeptjGk-3K-TuSwJtsbP-bP9veCCjVQXWL4yaZhcfLyD3mIkufVuDIPkEyklaXnaf-R2QWPJztxhQw59klKi-tCe18WhHLDE1UWOfI1jw2JY0mxiKMkEs1CKz6isfPWX72vVdYVWE458hUjTTv9mDhWsR4l8brMnPKMhCHlpcP7UDtCVNleaP9fR3-uaUvHgLwRVjfwalVMbrNXJfVRxwzx9SUhuC2QaaKO0fvnHjL8Lxp03uON-0mYYK75v_VnQTQzRiKvInuAb8vfFTBROlJZAPhVQ"
            ),
            "x-cloud-categoryid": "D06189A1-69AF-4D17-AC5B-480F7589D427",
            "x-cloud-categorytypeid": "CATEGORY_TYPE_BRIEFINGS",
            "x-cloud-client-timezone": "Asia/Calcutta",
            "x-cloud-context-timezone": "America/Los_Angeles",
            "x-cloud-customerid": "131393dd-0449-4cca-8528-2fed6b79eaed",
            "x-cloud-eventid": "E56114C1-02BD-4492-B3AF-65E2B82EF9D8",
            "x-cloud-requested-timezone": "America/Los_Angeles",
            "x_cloud_user": "surya.yadavalli@briefingiq.com",
        }

    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()


def get_report_data(fromDate=None, toDate=None, lookupType=None, headers=None):
    """
    Fetch admin report data within the provided date range.
    """
    base_url = (
        "https://briefings.briefingiq.com/"
        "events/api/admin/reports/8facc792-add1-481f-97ef-d4d815a7cbe7/data"
    )

    params = {}
    if fromDate:
        params["fromDate"] = fromDate
    if toDate:
        params["toDate"] = toDate
    if lookupType:
        params["lookupType"] = lookupType

    if headers is None or not headers:
        headers = {
            "accept": "application/json, text/plain, */*",
            "authorization": (
                "Bearer "
                "eyJraWQiOiJCQzFMVUlVOE1HRHF1MUZ1LTdYZmZGSnlWQmI4Q2dsdWpRYWxybXg4Z2RzIiwiYWxnIjoiUlMyNTYifQ.eyJ2ZXIiOjEsImp0aSI6IkFULlVtLVVESnVENXhwc0lHcEJSRjhBa1UzZmloZFlNOGR6M2h4NWFxWGNSLU0ub2FyM2JwMHc5Znh5TTVCbzU2OTciLCJpc3MiOiJodHRwczovL3RyaWFsLTczMDExNDAub2t0YS5jb20vb2F1dGgyL2RlZmF1bHQiLCJhdWQiOiJhcGk6Ly9kZWZhdWx0IiwiaWF0IjoxNzYyODUzMTEzLCJleHAiOjE3NjI4NTY3MTMsImNpZCI6IjBvYXg3dGdsbXJZMEo0Ujd5Njk3IiwidWlkIjoiMDB1eDl3ZWVpYlhFMlA4c2g2OTciLCJzY3AiOlsib3BlbmlkIiwib2ZmbGluZV9hY2Nlc3MiLCJwcm9maWxlIl0sImF1dGhfdGltZSI6MTc2Mjg1MzExMCwic3ViIjoic3VyeWEueWFkYXZhbGxpQGJyaWVmaW5naXEuY29tIn0.tYCGtOk1ZnTf3AAH1ppGDYDR5jhkFAM4FcM17bEzE-8fRPqTmj-ejx6o57rQhrwHFVk3Odf1CsPMj7xELqeEq-11qy7kA7vxA5Ickq7VD-jDiwlyrWj09BwRYVj6Ziiroq-jw5aXmwGxA2E2Bp8z-E8b5S8yWRR55BryEsE9QyhATJ6_beoMOKlCDvW26UrVpOEaz9DNTBFpqJ0pG_ECVcIeikG8CuKjHRXjfP3zhzVMY9pDhVRsGOdRTeLPdfzwvBybyjNzxEmY6jBqJbjRZkwm9PMwSeLRyBtMkH9Tr0xyBuzdkLNCDCjOm-eQlcyiCgJzziWMq-SU38FtYh8ytg"
            ),
            "x-cloud-categoryid": "72DCAF42-C7C0-4006-8F31-7952185E5D61",
            "x-cloud-categorytypeid": "CATEGORY_TYPE_BRIEFINGS",
            "x-cloud-client-timezone": "Asia/Calcutta",
            "x-cloud-context-timezone": "America/Los_Angeles",
            "x-cloud-customerid": "131393dd-0449-4cca-8528-2fed6b79eaed",
            "x-cloud-requested-timezone": "America/Los_Angeles",
            "x_cloud_user": "surya.yadavalli@briefingiq.com",
        }

    response = requests.get(base_url, headers=headers, params=params or None)
    response.raise_for_status()
    return response.json()


def format_chart(chart_type, title, x_axis_data, series_data, y_axis_title=None):
    """
    Generate Highcharts configuration JSON for frontend rendering.
    
    Args:
        chart_type: Type of chart (bar, column, line, pie, area)
        title: Chart title
        x_axis_data: List of category labels for x-axis
        series_data: List of series objects with 'name' and 'data' keys
        y_axis_title: Optional y-axis label
    
    Returns:
        Dict with type='highcharts' and config for frontend to render
    
    Reference: https://api.highcharts.com/highcharts/
    """
    # Base config following Highcharts API structure
    highcharts_config = {
        "chart": {
            "type": chart_type
        },
        "title": {
            "text": title
        },
        "xAxis": {
            "categories": x_axis_data,
            "crosshair": True
        },
        "yAxis": {
            "min": 0,
            "title": {
                "text": y_axis_title or "Value"
            }
        },
        "tooltip": {
            "shared": True
        },
        "series": series_data,
        "plotOptions": {},
        "legend": {
            "enabled": len(series_data) > 1 if series_data else False
        },
        "credits": {
            "enabled": False
        }
    }
    
    # Chart-type specific plotOptions
    if chart_type in ["bar", "column"]:
        highcharts_config["plotOptions"][chart_type] = {
            "dataLabels": {
                "enabled": True
            },
            "borderRadius": 3
        }
    elif chart_type == "line":
        highcharts_config["plotOptions"]["line"] = {
            "dataLabels": {
                "enabled": True
            },
            "marker": {
                "enabled": True
            }
        }
    elif chart_type == "area":
        highcharts_config["plotOptions"]["area"] = {
            "fillOpacity": 0.5
        }
    elif chart_type == "pie":
        # Pie charts need data in {name, y} format per Highcharts spec
        if series_data and len(series_data) > 0:
            pie_data = []
            for i, category in enumerate(x_axis_data):
                value = series_data[0]["data"][i] if i < len(series_data[0]["data"]) else 0
                pie_data.append({"name": category, "y": value})
            highcharts_config["series"] = [{
                "name": series_data[0].get("name", "Data"),
                "colorByPoint": True,
                "data": pie_data
            }]
        # Pie charts don't use xAxis
        highcharts_config.pop("xAxis", None)
        highcharts_config["plotOptions"]["pie"] = {
            "allowPointSelect": True,
            "cursor": "pointer",
            "dataLabels": {
                "enabled": True,
                "format": "<b>{point.name}</b>: {point.y}"
            },
            "showInLegend": True
        }
        highcharts_config["legend"]["enabled"] = True
        highcharts_config["tooltip"] = {
            "pointFormat": "<b>{point.y}</b> ({point.percentage:.1f}%)"
        }
    
    return {
        "type": "highcharts",
        "config": highcharts_config
    }


def format_response_as_markdown(response_text: str, input_list: list) -> str:
    """
    Format the response text as markdown, enhancing it with tables from SQL results.
    """
    formatted = response_text
    
    # Look for SQL query results in the input_list and format them as tables
    for item in input_list:
        # Handle both dict and Pydantic model objects
        if hasattr(item, 'model_dump'):
            # Pydantic model - convert to dict
            item_dict = item.model_dump()
        elif isinstance(item, dict):
            # Already a dict
            item_dict = item
        else:
            # Skip if we can't convert
            continue
        
        if item_dict.get("type") == "function_call_output" and "output" in item_dict:
            try:
                output_data = json.loads(item_dict["output"])
                if "query_database" in output_data:
                    db_result = output_data["query_database"]
                    if isinstance(db_result, dict) and "rows" in db_result and db_result["rows"]:
                        rows = db_result["rows"]
                        columns = db_result.get("columns", [])
                        
                        if rows and columns:
                            # Create markdown table
                            table_lines = []
                            # Header
                            table_lines.append("| " + " | ".join(columns) + " |")
                            table_lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
                            # Rows (limit to 50 rows for readability)
                            for row in rows[:50]:
                                row_values = []
                                for col in columns:
                                    value = row.get(col, "")
                                    # Convert to string and escape pipe characters
                                    value_str = str(value) if value is not None else ""
                                    value_str = value_str.replace("|", "\\|").replace("\n", " ")
                                    # Truncate long values
                                    if len(value_str) > 100:
                                        value_str = value_str[:97] + "..."
                                    row_values.append(value_str)
                                table_lines.append("| " + " | ".join(row_values) + " |")
                            
                            if len(rows) > 50:
                                table_lines.append(f"\n*Showing 50 of {len(rows)} rows*")
                            
                            table_md = "\n".join(table_lines)
                            
                            # Insert table after the response if it's not already there
                            if table_md not in formatted:
                                formatted += f"\n\n### Query Results\n\n{table_md}"
            except (json.JSONDecodeError, KeyError, TypeError):
                # Skip if we can't parse the output
                continue
    
    return formatted


def process_query(query, schedule_headers=None, session_id=None):
    logger.info(f"Starting process_query with query: {query[:100]}... (session_id: {session_id})")
    
    # Get or create session
    if session_id is None:
        session_id = str(uuid.uuid4())
        logger.info(f"Generated new session_id: {session_id}")
    
    # Initialize session if it doesn't exist
    if session_id not in chat_sessions:
        chat_sessions[session_id] = []
        logger.info(f"Created new chat session: {session_id}")
    
    # Get conversation history for this session
    conversation_history = chat_sessions[session_id]
    
    # Build input_list: start with conversation history, then add new query
    input_list = conversation_history.copy()
    input_list.append({"role": "user", "content": query})

    # Track chart data if format_chart is called
    chart_data = None

    iteration_count = 0
    while True:
        iteration_count += 1
        logger.info(f"\n{'='*60}")
        logger.info(f"ITERATION {iteration_count}")
        logger.info(f"{'='*60}")
        logger.info(f"Input to API:")
        logger.info(f"{json_dumps_safe(input_list)}")

        response = client.responses.create(
            model="gpt-4.1-mini",
            tools=tools,
            input=input_list,
            instructions="""
            You are a Senior business analyst and scheduling expert. You are given a user query. 

            CRITICAL TOOL RULES:
            - If the query is about meetings, attendees, schedules, or opportunity metrics, you MUST call the `query_database` tool. Do NOT answer directly. 
            - For other queries (like GDP or general info), use the appropriate tool (`get_gdp` or `schedule_meeting`) if needed. 
            - Do NOT invent answers; always rely on tools when relevant.
            
            CHART/VISUALIZATION RULES:
            - If the user asks for a chart, graph, bar chart, pie chart, or any visualization:
              1. First call `query_database` to get the data
              2. Then call `format_chart` with the retrieved data to generate a Highcharts config
            - Choose appropriate chart types:
              - bar/column: for comparing categories
              - line: for trends over time
              - pie: for showing parts of a whole
              - area: for cumulative data over time
            - Extract x_axis_data (category labels) and series_data (numeric values) from query results

            MARKDOWN RULES:
            - return the final response in markdown format.
            - When returning raw tool outputs or function call results, do NOT use markdown. Keep it JSON/plain text for internal processing. 
            - When formatting in markdown, follow these rules:
                1. **Headers**: Use ## for main sections, ### for subsections
                Example: ## GDP Information
                2. **Bold text**: Use **text** for emphasis on key numbers
                Example: The GDP is **$29,167.78 billion**
                3. **Lists**: Use - for bullet points or 1. 2. 3. for numbered lists
                Example:
                - GDP Growth: 2.8%
                - GDP per capita: $86,601.28
                4. **Code blocks**: Use ``` for SQL or code snippets
                Example: ```sql
                SELECT * FROM table
                ```
                5. **Numbers and statistics**: Always bold key metrics

            ALWAYS ensure your final response is clear, concise, and only uses markdown where appropriate for readability. Never markdown tool outputs.
            """
            ,
        )

        logger.info(f"Raw API Response Output:")
        logger.info(f"{json_dumps_safe(response.output)}")

        input_list += response.output

        pending_calls = [item for item in response.output if item.type == "function_call"]

        if not pending_calls:
            logger.debug("No pending function calls, breaking loop")
            # Extract the final response text from the last iteration
            final_response_text = ""
            if hasattr(response, 'output_text'):
                final_response_text = response.output_text
            else:
                # Fallback: extract from output messages
                for item in reversed(response.output):
                    if hasattr(item, 'content') and item.content:
                        for content_item in item.content:
                            if hasattr(content_item, 'text'):
                                final_response_text = content_item.text
                                break
                        if final_response_text:
                            break
                    elif hasattr(item, 'type') and item.type == "message":
                        if hasattr(item, 'content') and isinstance(item.content, list):
                            for content_item in item.content:
                                if isinstance(content_item, dict) and content_item.get("type") == "output_text":
                                    final_response_text = content_item.get("text", "")
                                    break
                        if final_response_text:
                            break
            
            logger.info(f"\n{'='*60}")
            logger.info(f"FINAL OUTPUT")
            logger.info(f"{'='*60}")
            logger.info(f"Final Output Text:")
            logger.info(f"{final_response_text}")
            if chart_data:
                logger.info(f"Chart Data: {chart_data.get('type', 'unknown')} chart included")
            logger.info(f"{'='*60}\n")
            
            # Format response as markdown (adds SQL tables if needed)
            #formatted_response = format_response_as_markdown(final_response_text, input_list)
            
            # Update conversation history: add user query and assistant response
            # Only keep last 20 messages to prevent context from growing too large
            chat_sessions[session_id].append({"role": "user", "content": query})
            chat_sessions[session_id].append({"role": "assistant", "content": final_response_text})
            
            # Trim to last 20 messages (10 exchanges)
            if len(chat_sessions[session_id]) > 20:
                chat_sessions[session_id] = chat_sessions[session_id][-20:]
                logger.info(f"Trimmed conversation history for session {session_id}")
            
            logger.info(f"Query processed successfully, response length: {len(final_response_text)} characters")
            logger.info(f"Session {session_id} now has {len(chat_sessions[session_id])} messages in history")
            
            # Return response with optional chart data
            # If chart_data exists, return dict with both text and chart
            # Otherwise return just the text for backward compatibility
            if chart_data:
                return {
                    "text": final_response_text,
                    "chart": chart_data,  # Contains {type: "highcharts", config: {...}}
                    "type": "chart",
                }
            return {
                "text": final_response_text,
                "type": "text",
            }

        logger.info(f"Processing {len(pending_calls)} function call(s)")
        for item in pending_calls:
            args = json.loads(item.arguments) if item.arguments else {}
            logger.info(f"→ Calling function: {item.name} with args: {json.dumps(args, indent=2)}")
            
            if item.name == "get_horoscope":
                horoscope = get_horoscope(args)
                output = {"horoscope": horoscope}
                logger.info(f"✓ {item.name} returned: {json.dumps(output, indent=2)}")
                input_list.append({
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": json_dumps_safe(output)
                })

            elif item.name == "get_gdp":
                gdp = get_gdp(args["country"], args["year"])
                output = {"gdp": gdp}
                logger.info(f"✓ {item.name} returned: {json.dumps(output, indent=2)}")
                input_list.append({
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": json_dumps_safe(output)
                })

            elif item.name == "schedule_meeting":
                try:
                    result = schedule_meeting(
                        args["calendarFromDateIso"],
                        args["calendarStartTimeIso"],
                        args["calendarEndTimeIso"],
                        args["calendarToDateIso"],
                        args.get("calendarType", "BLOCKED"),
                        args.get("comments"),
                        schedule_headers,
                    )
                    tool_output = {"schedule_meeting": result}
                    logger.info(f"✓ {item.name} returned: {json.dumps(tool_output, indent=2)}")
                except Exception as e:
                    logger.error(f"✗ Error in {item.name}: {e}", exc_info=True)
                    tool_output = {"error": str(e)}

                input_list.append({
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": json_dumps_safe(tool_output)
                })

            elif item.name == "get_calendars":
                try:
                    result = get_calendars()
                    tool_output = {"get_calendars": result}
                    # Truncate large outputs for readability
                    output_str = json.dumps(tool_output, indent=2)
                    if len(output_str) > 500:
                        logger.info(f"✓ {item.name} returned: {output_str[:500]}... (truncated, {len(output_str)} chars total)")
                    else:
                        logger.info(f"✓ {item.name} returned: {output_str}")
                except Exception as e:
                    logger.error(f"✗ Error in {item.name}: {e}", exc_info=True)
                    tool_output = {"error": str(e)}

                input_list.append({
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": json_dumps_safe(tool_output)
                })

            elif item.name == "get_resources":
                try:
                    result = get_resources(
                        args["resource_type_id"],
                        schedule_headers
                    )
                    tool_output = {"get_resources": result}
                    output_str = json.dumps(tool_output, indent=2)
                    if len(output_str) > 500:
                        logger.info(f"✓ {item.name} returned: {output_str[:500]}... (truncated, {len(output_str)} chars total)")
                    else:
                        logger.info(f"✓ {item.name} returned: {output_str}")
                except Exception as e:
                    logger.error(f"✗ Error in {item.name}: {e}", exc_info=True)
                    tool_output = {"error": str(e)}

                input_list.append({
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": json_dumps_safe(tool_output)
                })

            elif item.name == "get_report_data":
                try:
                    result = get_report_data(
                        args.get("fromDate"),
                        args.get("toDate"),
                        args.get("lookupType"),
                        schedule_headers,
                    )
                    tool_output = {"get_report_data": result}
                    output_str = json.dumps(tool_output, indent=2)
                    if len(output_str) > 500:
                        logger.info(f"✓ {item.name} returned: {output_str[:500]}... (truncated, {len(output_str)} chars total)")
                    else:
                        logger.info(f"✓ {item.name} returned: {output_str}")
                except Exception as e:
                    logger.error(f"✗ Error in {item.name}: {e}", exc_info=True)
                    tool_output = {"error": str(e)}

                input_list.append({
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": json_dumps_safe(tool_output)
                })

            elif item.name == "oracle_financial_stats":
                try:
                    result = oracle_financial_stats(args["year"])
                    tool_output = {"oracle_financial_stats": result}
                    logger.info(f"✓ {item.name} returned: {json.dumps(tool_output, indent=2)}")
                except Exception as e:
                    logger.error(f"✗ Error in {item.name}: {e}", exc_info=True)
                    tool_output = {"error": str(e)}

                input_list.append({
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": json_dumps_safe(tool_output)
                })

            elif item.name == "get_fruits":
                try:
                    result = get_fruits()
                    tool_output = {"get_fruits": result}
                    logger.info(f"✓ {item.name} returned: {json.dumps(tool_output, indent=2)}")
                except Exception as e:
                    logger.error(f"✗ Error in {item.name}: {e}", exc_info=True)
                    tool_output = {"error": str(e)}

                input_list.append({
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": json_dumps_safe(tool_output)
                })

            elif item.name == "add_fruit":
                try:
                    result = add_fruit(args["fruit"])
                    tool_output = {"add_fruit": result}
                    logger.info(f"✓ {item.name} returned: {json.dumps(tool_output, indent=2)}")
                except Exception as e:
                    logger.error(f"✗ Error in {item.name}: {e}", exc_info=True)
                    tool_output = {"error": str(e)}

                input_list.append({
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": json_dumps_safe(tool_output)
                })

            elif item.name == "query_database":
                try:
                    result = ask_sqlite(args["question"])
                    tool_output = {"query_database": result}
                    output_str = json.dumps(tool_output, indent=2, default=str)
                    if len(output_str) > 1000:
                        logger.info(f"✓ {item.name} returned: {output_str[:1000]}... (truncated, {len(output_str)} chars total)")
                    else:
                        logger.info(f"✓ {item.name} returned: {output_str}")
                except Exception as e:
                    logger.error(f"✗ Error in {item.name}: {e}", exc_info=True)
                    tool_output = {"error": str(e)}

                input_list.append({
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": json_dumps_safe(tool_output)
                })

            elif item.name == "format_chart":
                try:
                    result = format_chart(
                        args["chart_type"],
                        args["title"],
                        args["x_axis_data"],
                        args["series_data"],
                        args.get("y_axis_title")
                    )
                    tool_output = {"format_chart": result}
                    # Store chart data for return
                    chart_data = result
                    logger.info(f"✓ {item.name} returned Highcharts config for '{args['chart_type']}' chart")
                except Exception as e:
                    logger.error(f"✗ Error in {item.name}: {e}", exc_info=True)
                    tool_output = {"error": str(e)}

                input_list.append({
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": json_dumps_safe(tool_output)
                })


def handle_query(query, headers, session_id=None):
    return process_query(query, headers, session_id=session_id)


if __name__ == "__main__":
    sample_query_1 = "fetch all resources for this id: EEF43C5C-B5E6-41C6-9634-8D812AC43FC8"
    sample_query_2 = "schedule a meeting for me on 2025-11-28 from 9:00 to 9:30 with comments that TEST67"
    sample_query_3 = "what is the GDP of USA in 2024? and what is my horoscope? and fetch all resources for this id: EEF43C5C-B5E6-41C6-9634-8D812AC43FC8"
    sample_query_4 = "pull the stats for financial year 2024 and 2025. compare the stats and give me insights"
    sample_query_5 = "check if the date december 10th 2025 is available if so then schedule a meeting for an 1hr of any time on that day with comments that TEST6767"
    sample_query_6 = "check if jackfruit is in the list of fruits if not then add it to the list"
    sample_query_7 = "list fruits"
    sample_query_8 = "show me the report data from october 5th to november 10th and break it down by line of business."
    sample_query_9 = "how many meetings are submitted this month ?"
    sample_query_10 = "chcek if ibm visit on dec 14 has all presenters assigned"
    sample_query_11 = "how many meeting are submitted this month and last month compare?"
    
    # Database query prompts - Operations & Meeting Queries (based on actual DB data)
    db_query_1 = "How many events does Nvidia have compared to Apple?"
    db_query_2 = "What is the breakdown of events by region? Show me how many events are in EMEA, North America, LAD, and JAPAC."
    db_query_3 = "Which events are assigned to Robert Smith and what are the customer names and start dates?"
    db_query_4 = "How many events are there per line of business? Show me the count for NACI, Marketing, CAGBU, and Glueck."
    db_query_5 = "List all events scheduled for November 2025 with their customer names, regions, and tech managers."
    
    # Database query prompts - Attendee Analysis Queries (based on actual DB data)
    db_query_6 = "Show me how many decision makers each company has. Which companies have the most decision makers in their events?"
    db_query_7 = "Show me all attendees for Barclays events, including their names, whether they are decision makers, influencers, or technical, and if they are remote or in-person."
    db_query_8 = "What is the breakdown of attendees by remote versus in-person? Show me the total count for each."
    db_query_9 = "Find all events where there are no decision makers in the attendee list. Show the customer name and event ID."
    db_query_10 = "How many attendees are Internal versus External across all events?"
    
    # Database query prompts - Revenue & Opportunity Queries (based on actual DB data)
    db_query_11 = "What is the total closed opportunity revenue across all events? Also show the average, minimum, and maximum."
    db_query_12 = "Show me all opportunities with probability of close greater than 75%. Include customer name and the probability percentage."
    db_query_13 = "What is the closed opportunity revenue for each company? Show me which companies have the highest revenue."
    db_query_14 = "How many opportunities have closed revenue between $300,000 and $500,000? Show the customer names and revenue amounts."
    
    # Database query prompts - Complex Multi-View Queries (based on actual DB data)
    db_query_15 = "Give me a complete analysis for Ford Motor: show all their events with dates, total attendees, number of decision makers, remote vs in-person count, and any associated revenue or opportunity data."
    
    # Chart/Visualization query prompts
    chart_query_1 = "Show me the number of decision makers per company as a bar chart"
    chart_query_2 = "Create a pie chart showing the breakdown of events by region"
    chart_query_3 = "Show me a column chart comparing the number of events per line of business"
    
    logger.info("Running test query")
    result = handle_query(db_query_15, None)
    logger.info(f"Test query result: {result[:200]}...")  # Log first 200 chars






