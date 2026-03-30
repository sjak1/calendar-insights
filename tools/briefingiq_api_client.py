"""
BriefingIQ API Client - Fetch events directly from API instead of database.
This provides consistent data with the frontend and includes attendee information.
"""

import requests
import time
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from logging_config import get_logger

logger = get_logger(__name__)

# Cache for API responses (shorter TTL since it's real-time data)
_API_CACHE: Dict[str, tuple] = {}
_API_CACHE_TTL = 120  # 2 minutes

# API Configuration
BASE_URL = "https://briefings.briefingiq.com/events/api"


def fetch_events_from_briefingiq_api(
    category_id: str,
    headers: Dict[str, str],
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    status: Optional[str] = None,
    category_name: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Fetch events from BriefingIQ API for a specific category.

    Args:
        category_id: Category UUID (e.g., 72DCAF42-C7C0-4006-8F31-7952185E5D61)
        headers: Request headers including Authorization and X-Cloud-* headers
        from_date: Start date in ISO format (defaults to today)
        to_date: End date in ISO format (defaults to +30 days)
        status: Optional status filter (CONFIRMED, SUBMITTED, HOLD, etc.)

    Returns:
        Dict with events data or None if failed
    """
    if not category_id:
        logger.error("No category_id provided for API call")
        return None

    # Set default date range if not provided
    if not from_date:
        from_date = datetime.now().strftime("%Y-%m-%dT00:00:00")
    if not to_date:
        to_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%dT00:00:00")

    # Build cache key
    cache_key = f"{category_id}_{from_date}_{to_date}_{status}"

    # Check cache
    if cache_key in _API_CACHE:
        timestamp, cached_data = _API_CACHE[cache_key]
        if time.time() - timestamp < _API_CACHE_TTL:
            logger.debug(f"Using cached API data for category {category_id}")
            return cached_data

    # Build URL and parameters
    url = f"{BASE_URL}/events"
    params = {
        "categoryid": category_id,
        "fromdate": from_date,
        "todate": to_date,
    }

    if status:
        params["status"] = status

    # Extract required headers from the request headers
    api_headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": headers.get("accept-language", "en-GB,en;q=0.8"),
        "Authorization": headers.get("authorization", headers.get("Authorization", "")),
        "X-Cloud-Categoryid": category_id,
        "X-Cloud-Categorytypeid": headers.get(
            "x-cloud-categorytypeid", "CATEGORY_TYPE_BRIEFINGS"
        ),
        "X-Cloud-Client-Timezone": headers.get(
            "x-cloud-client-timezone", "America/Los_Angeles"
        ),
        "X-Cloud-Context-Timezone": headers.get(
            "x-cloud-context-timezone", "America/Los_Angeles"
        ),
        "X-Cloud-Customerid": headers.get("x-cloud-customerid", ""),
        "X-Cloud-Requested-Timezone": headers.get(
            "x-cloud-requested-timezone", "America/Los_Angeles"
        ),
        "X_cloud_user": headers.get("x_cloud_user", headers.get("X_cloud_user", "")),
        "User-Agent": headers.get("user-agent", "Mozilla/5.0"),
        "Referer": "https://briefings.briefingiq.com/events/",
        "Origin": "https://briefings.briefingiq.com",
    }

    logger.info(f"🌐 Calling BriefingIQ API for category {category_id}")
    logger.debug(f"URL: {url}, Params: {params}")

    try:
        response = requests.get(url, headers=api_headers, params=params, timeout=30)

        logger.info(
            f"📊 API Response: {response.status_code}, Size: {len(response.content)} bytes"
        )

        if response.status_code == 200:
            data = response.json()

            # Parse HAL format with category name
            parsed_data = _parse_hal_response(data, category_name)

            # Cache successful response
            _API_CACHE[cache_key] = (time.time(), parsed_data)

            logger.info(
                f"✅ Successfully fetched {parsed_data['summary']['total_events']} events from API"
            )
            return parsed_data

        elif response.status_code == 401:
            logger.error("❌ API Authentication failed - token may be expired")
            return None
        elif response.status_code == 403:
            logger.error("❌ API Access forbidden - check permissions")
            return None
        else:
            logger.error(f"❌ API Error {response.status_code}: {response.text[:200]}")
            return None

    except requests.exceptions.Timeout:
        logger.error("❌ API request timed out")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ API request failed: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Unexpected error in API call: {e}", exc_info=True)
        return None


def _parse_hal_response(
    data: Dict[str, Any], category_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Parse HAL JSON response format from BriefingIQ API.

    Returns structured data with events, summary, and metadata.
    """
    result = {
        "category_name": category_name or "Briefings",
        "events": [],
        "summary": {
            "total_events": 0,
            "total_attendees": 0,
            "total_groups": 0,
            "confirmed_count": 0,
            "submitted_count": 0,
            "hold_count": 0,
        },
        "groups": [],
    }

    try:
        # Extract event groups from HAL format
        if "_embedded" in data and "eventGroups" in data["_embedded"]:
            event_groups = data["_embedded"]["eventGroups"]
            result["summary"]["total_groups"] = len(event_groups)

            for group in event_groups:
                group_name = group.get("group", "Unknown")
                events = group.get("events", [])

                group_data = {
                    "name": group_name,
                    "event_count": len(events),
                    "events": [],
                }

                for event in events:
                    # Extract event details
                    event_data = _extract_event_details(event)
                    result["events"].append(event_data)
                    group_data["events"].append(event_data)

                    # Update summary counts
                    result["summary"]["total_events"] += 1
                    result["summary"]["total_attendees"] += event_data.get(
                        "attendee_count", 0
                    )

                    # Count by status
                    status = event_data.get("status", "").upper()
                    if status == "CONFIRMED":
                        result["summary"]["confirmed_count"] += 1
                    elif status == "SUBMITTED":
                        result["summary"]["submitted_count"] += 1
                    elif status == "HOLD":
                        result["summary"]["hold_count"] += 1

                result["groups"].append(group_data)

        logger.debug(
            f"Parsed {result['summary']['total_events']} events from API response"
        )
        return result

    except Exception as e:
        logger.error(f"Error parsing API response: {e}", exc_info=True)
        return result


def _extract_event_details(event: Dict[str, Any]) -> Dict[str, Any]:
    """Extract relevant details from an event object."""

    # Get event name (could be in various fields)
    event_name = (
        event.get("eventName")
        or event.get("event_name")
        or event.get("title")
        or event.get("subject")
        or event.get("name")
        or ""
    )

    # Get customer name
    customer_name = (
        event.get("customerName") or event.get("customer_name") or "(unnamed)"
    )

    # Combine event name and customer name for display
    display_name = event_name or customer_name or "(unnamed)"

    # Get event ID
    event_id = event.get("id") or event.get("uniqueId") or ""

    # Get status
    status_obj = event.get("status", {})
    status = status_obj.get("stateName") or status_obj.get("uniqueId") or "Unknown"

    # Get dates
    start_date = None
    end_date = None

    if event.get("startDate"):
        start_obj = event["startDate"]
        # Prefer client's timezone
        if start_obj.get("client") and start_obj["client"].get("clientZoneDate"):
            start_date = start_obj["client"]["clientZoneDate"]
        elif start_obj.get("zoneDate"):
            start_date = start_obj["zoneDate"]

    if event.get("endDate"):
        end_obj = event["endDate"]
        if end_obj.get("client") and end_obj["client"].get("clientZoneDate"):
            end_date = end_obj["client"]["clientZoneDate"]
        elif end_obj.get("zoneDate"):
            end_date = end_obj["zoneDate"]

    # Get attendees
    attendees = event.get("attendees", [])
    attendee_count = len(attendees)

    # Count decision makers and technical attendees
    decision_makers = sum(
        1 for a in attendees if a.get("isDecisionMaker") or a.get("decisionMaker")
    )
    technical = sum(1 for a in attendees if a.get("isTechnical") or a.get("technical"))

    # Get location
    location = ""
    if event.get("location"):
        location = event["location"].get("name") or event["location"].get(
            "locationName", ""
        )

    # Get opportunity info
    opportunity_value = 0
    if event.get("opportunity"):
        opp = event["opportunity"]
        opportunity_value = opp.get("opportunityRevenue") or opp.get("revenue", 0)

    return {
        "event_id": event_id,
        "event_name": event_name,
        "customer_name": customer_name,
        "display_name": display_name,
        "status": status,
        "start_date": start_date,
        "end_date": end_date,
        "attendee_count": attendee_count,
        "decision_makers": decision_makers,
        "technical_count": technical,
        "location": location,
        "opportunity_value": opportunity_value,
        "raw_data": event,  # Keep raw data for detailed queries
    }


def build_api_based_context(
    query: str, api_data: Dict[str, Any], user_info: Optional[Dict[str, str]] = None
) -> str:
    """
    Build context string for LLM from API data.

    Args:
        query: User's query
        api_data: Parsed API response data
        user_info: Optional user context (email, timezone, etc.)

    Returns:
        Context string for LLM
    """
    category_name = api_data.get("category_name", "Briefings")
    summary = api_data.get("summary", {})
    events = api_data.get("events", [])
    groups = api_data.get("groups", [])

    # Build user context section
    user_context = ""
    if user_info:
        user_context = f"\nUser: {user_info.get('email', 'Unknown')}\n"
        if user_info.get("client_timezone"):
            user_context += f"Timezone: {user_info.get('client_timezone')}\n"

    # Build summary section
    summary_text = f"""{category_name} Category Summary:
• {summary.get("total_events", 0)} total events ({summary.get("confirmed_count", 0)} confirmed, {summary.get("submitted_count", 0)} submitted, {summary.get("hold_count", 0)} on hold)
• {summary.get("total_attendees", 0)} total attendees"""

    # Build events list
    events_text = "Recent Events:\n"
    for i, event in enumerate(events[:15], 1):
        name = event.get("customer_name", "(unnamed)")
        status = event.get("status", "Unknown")
        attendees = event.get("attendee_count", 0)
        dms = event.get("decision_makers", 0)
        date = event.get("start_date", "")

        events_text += f"{i}. {name}"
        if date:
            events_text += f" ({date.split('T')[0] if 'T' in str(date) else date})"
        events_text += f" - {status}"
        if attendees > 0:
            events_text += f", {attendees} attendees"
            if dms > 0:
                events_text += f" ({dms} DMs)"
        events_text += "\n"

    if len(events) > 15:
        events_text += f"... and {len(events) - 15} more events\n"

    # Build actions section
    actions_text = """Available Actions:
• Query specific events by date range, status, or attendees
• Generate agenda for any event
• Compare multiple events
• Get category analytics and insights"""

    # Combine all sections
    context = f"""{query}

[Context: User is viewing {category_name} category.{user_context}
{summary_text}

{events_text}
{actions_text}]"""

    return context


def determine_date_range_from_query(query: str) -> tuple:
    """
    Determine appropriate date range based on user query.

    Returns:
        tuple: (from_date, to_date) in ISO format
    """
    query_lower = query.lower()
    now = datetime.now()

    # This week
    if any(phrase in query_lower for phrase in ["this week", "current week", "week"]):
        from_date = now.strftime("%Y-%m-%dT00:00:00")
        to_date = (now + timedelta(days=7)).strftime("%Y-%m-%dT23:59:59")
        return from_date, to_date

    # Next week
    if "next week" in query_lower:
        from_date = (now + timedelta(days=7)).strftime("%Y-%m-%dT00:00:00")
        to_date = (now + timedelta(days=14)).strftime("%Y-%m-%dT23:59:59")
        return from_date, to_date

    # This month
    if any(
        phrase in query_lower for phrase in ["this month", "current month", "month"]
    ):
        from_date = now.strftime("%Y-%m-%dT00:00:00")
        to_date = (now + timedelta(days=30)).strftime("%Y-%m-%dT23:59:59")
        return from_date, to_date

    # Next month
    if "next month" in query_lower:
        from_date = (now + timedelta(days=30)).strftime("%Y-%m-%dT00:00:00")
        to_date = (now + timedelta(days=60)).strftime("%Y-%m-%dT23:59:59")
        return from_date, to_date

    # Today
    if any(phrase in query_lower for phrase in ["today", "now"]):
        from_date = now.strftime("%Y-%m-%dT00:00:00")
        to_date = now.strftime("%Y-%m-%dT23:59:59")
        return from_date, to_date

    # Tomorrow
    if "tomorrow" in query_lower:
        from_date = (now + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00")
        to_date = (now + timedelta(days=1)).strftime("%Y-%m-%dT23:59:59")
        return from_date, to_date

    # Yesterday/Past (for completed events)
    if any(
        phrase in query_lower for phrase in ["past", "completed", "done", "yesterday"]
    ):
        from_date = (now - timedelta(days=365)).strftime("%Y-%m-%dT00:00:00")
        to_date = now.strftime("%Y-%m-%dT23:59:59")
        return from_date, to_date

    # Default: Next 30 days
    from_date = now.strftime("%Y-%m-%dT00:00:00")
    to_date = (now + timedelta(days=30)).strftime("%Y-%m-%dT23:59:59")
    return from_date, to_date


if __name__ == "__main__":
    # Test the module
    print("Testing BriefingIQ API client...")

    # This would need real headers to work
    test_headers = {
        "authorization": "Bearer test_token",
        "x_cloud_user": "test@example.com",
    }

    result = fetch_events_from_briefingiq_api(
        category_id="72DCAF42-C7C0-4006-8F31-7952185E5D61",
        headers=test_headers,
    )

    if result:
        print(f"✅ Success! Got {result['summary']['total_events']} events")
        print(f"   Attendees: {result['summary']['total_attendees']}")
    else:
        print("❌ Failed to fetch data (expected without valid token)")
