"""
BriefingIQ API integrations.
"""
import requests


def schedule_meeting(
    calendarFromDateIso,
    calendarStartTimeIso,
    calendarEndTimeIso,
    calendarToDateIso,
    calendarType="BLOCKED",
    comments=None,
    headers=None,
):
    """Create blocked calendar time using BriefingIQ API."""
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
    """Fetch schedules for the configured resource using BriefingIQ API."""
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
