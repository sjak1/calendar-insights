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
        "description": "schedules meeting in calender from date to date and time to time",
        "parameters": {
            "type": "object",
            "properties":{
                "calendarFromDate": {
                    "type": "int",
                    "description": "meetign start date in milliseconds"
                },
                "calendarToDate": {
                    "type": "int",
                    "description": "meeting end date in milliseconds"
                },
                "calenderStartTime": {
                    "type": "int"
                    "description": "meeting start time in milliseconds"
                }
                "calenderEndTime": {
                    "type": "int"
                    "description": "meeting end time in milliseconds"
                }
            },
            "required": ["", ""],

        }
    }
]

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

def schedule_meeting(calendarFromDate, calendarToDate, calendarStartTime, calenderEndTime):

    url = "https://dev.briefingiq.com/event/api/resources/87F37A62-B1B8-466D-BABC-CA364EF4D371/calendars"

    headers = {
        "accept": "application/json",
        "x-cloud-customerid": "3",
        "X_cloud_user": "3",
        "Content-Type": "application/json"
    }

    data = {
        "calendarFromDate": 1760553600000,
        "calendarToDate": 1760812800000,
        "calendarStartTime": 3600000,
        "calendarEndTime": 10800000,
        "calendarType": "Blocked",
        "comments": "Test Comments"
    }

    response = requests.post(url, headers=headers, json=data)

    print(response.status_code)
    print(response.json())




input_list = [
    {"role": "user", "content": "what is the gdp of nepal in 2025. is that good or bad?"}
]

response = client.responses.create(
    model="gpt-5",
    tools=tools,
    input=input_list,
)

input_list += response.output

for item in response.output:
    if item.type == "function_call":
        if item.name == "get_horoscope":
            # 3. Execute the function logic for get_horoscope
            horoscope = get_horoscope(json.loads(item.arguments))
            
            # 4. Provide function call results to the model
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

print("Final input:")
print(input_list)

response = client.responses.create(
    model="gpt-5",
    instructions="respond based on the tool output in the style of a funny jamaican.",
    tools=tools,
    input=input_list,
)

# 5. The model should be able to give a response!
print("Final output:")
print(response.model_dump_json(indent=2))
print("\n" + response.output_text)





