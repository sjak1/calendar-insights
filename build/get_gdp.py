import requests
from openai import OpenAI
import json
from dotenv import load_dotenv
from datetime import datetime

from scripts.sqlite_qa import ask_sqlite

load_dotenv()

client = OpenAI()

tools = [
    {
        "type": "function",
        "name": "get_horoscope",
        "description": "get today's horoscope for an astrological sign.",
        "parameters": {
            "type": "object",
            "properties": {
                "sign": {
                    "type": "string",
                    "description": "an astrological sign like taurus or aquarius",
                },
            },
            "required": ["sign"],
        },
    },
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


def process_query(query, schedule_headers=None):

    input_list = [
        {"role": "user", "content": query}
    ]

    while True:  

        response = client.responses.create(
            model="gpt-4.1-mini",
            tools=tools,
            input=input_list,
        )

        print("response interation : ", response.output)

        input_list += response.output

        pending_calls = [item for item in response.output if item.type == "function_call"]

        if not pending_calls:
            break

        for item in pending_calls:
            if item.name == "get_horoscope":
                horoscope = get_horoscope(json.loads(item.arguments))
                input_list.append({
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": json.dumps({
                        "horoscope": horoscope
                    })
                })

            elif item.name == "get_gdp":
                args = json.loads(item.arguments)
                gdp = get_gdp(args["country"], args["year"])

                input_list.append({
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": json.dumps({
                        "gdp": gdp
                    })
                })

            elif item.name == "schedule_meeting":
                args = json.loads(item.arguments)
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
                except Exception as e:
                    tool_output = {"error": str(e)}

                input_list.append({
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": json.dumps(tool_output)
                })

            elif item.name == "get_calendars":
                try:
                    result = get_calendars()
                    tool_output = {"get_calendars": result}
                except Exception as e:
                    tool_output = {"error": str(e)}

                input_list.append({
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": json.dumps(tool_output)
                })

            elif item.name == "get_resources":
                args = json.loads(item.arguments)
                try:
                    result = get_resources(
                        args["resource_type_id"],
                        schedule_headers
                    )
                    tool_output = {"get_resources": result}
                except Exception as e:
                    tool_output = {"error": str(e)}

                input_list.append({
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": json.dumps(tool_output)
                })

            elif item.name == "get_report_data":
                args = json.loads(item.arguments)
                try:
                    result = get_report_data(
                        args.get("fromDate"),
                        args.get("toDate"),
                        args.get("lookupType"),
                        schedule_headers,
                    )
                    tool_output = {"get_report_data": result}
                except Exception as e:
                    tool_output = {"error": str(e)}

                input_list.append({
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": json.dumps(tool_output)
                })

            elif item.name == "oracle_financial_stats":
                args = json.loads(item.arguments)
                try:
                    result = oracle_financial_stats(args["year"])
                    tool_output = {"oracle_financial_stats": result}
                except Exception as e:
                    tool_output = {"error": str(e)}

                input_list.append({
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": json.dumps(tool_output)
                })

            elif item.name == "get_fruits":
                try:
                    result = get_fruits()
                    tool_output = {"get_fruits": result}
                except Exception as e:
                    tool_output = {"error": str(e)}

                input_list.append({
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": json.dumps(tool_output)
                })

            elif item.name == "add_fruit":
                args = json.loads(item.arguments)
                try:
                    result = add_fruit(args["fruit"])
                    tool_output = {"add_fruit": result}
                except Exception as e:
                    tool_output = {"error": str(e)}

                input_list.append({
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": json.dumps(tool_output)
                })

            elif item.name == "query_database":
                args = json.loads(item.arguments)
                try:
                    result = ask_sqlite(args["question"])
                    tool_output = {"query_database": result}
                except Exception as e:
                    tool_output = {"error": str(e)}

                input_list.append({
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": json.dumps(tool_output)
                })

    print("Final input:")
    print(input_list)


    response = client.responses.create(
        model="gpt-4.1-mini",
        instructions="you are an helpful assistant that can answer questions",
        input=input_list,
    )

    print("Final output:")
    print(response.model_dump_json(indent=2))
    print("\n" + response.output_text)
    return response.output_text


def handle_query(query, headers):
    return process_query(query, headers)


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
    
    print(handle_query(db_query_15, None))






