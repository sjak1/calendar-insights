import requests
from openai import OpenAI
import json
from dotenv import load_dotenv

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
    {
        "type": "function",
        "name": "get_resources",
        "description": "Fetch all resources of a specific resource type (e.g., Location, Presenter, Room) from BriefingIQ.",
        "parameters": {
            "type": "object",
            "properties": {
                "resource_type_id": {
                    "type": "string",
                    "description": "The unique ID of the resource type. Common IDs: EEF43C5C-B5E6-41C6-9634-8D812AC43FC8 (Location), f57aea4f-dc69-475b-b02d-96259c216699 (Presenter), EAC8F953-99D0-43DF-8E15-CA03F21EA92D (Room)"
                }
            },
            "required": ["resource_type_id"]
        }
    }
]

'''tools.append({
    "type": "function",
    "name": "get_calendars",
    "description": "Fetch calendars for the configured resource (GET; no payload).",
    "parameters": {"type": "object", "properties": {}, "required": []},
})'''

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


def process_query(query, schedule_headers=None):

    input_list = [
        {"role": "user", "content": query}
    ]

    response = client.responses.create(
        model="gpt-4.1-mini",
        tools=tools,
        input=input_list,
    )

    print("HERE IS THE OUTPUT AT FIRST CALL : ")
    print(response.output)

    input_list += response.output

    for item in response.output:
        if item.type == "function_call":
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

    print("Final input:")
    print(input_list)

    response = client.responses.create(
        model="gpt-4.1-mini",
        instructions="respond based on the tool output as a professional ai assistant",
        tools=tools,
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
    print(handle_query(sample_query_2, None))





