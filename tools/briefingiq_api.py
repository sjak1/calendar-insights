"""
BriefingIQ API integrations — admin reports only.

Scheduling / calendar / resource functions have moved to tools.briefingiq_writer,
which reads auth + tenant context from the incoming request headers instead of
hardcoded bearer tokens.
"""
import requests


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
