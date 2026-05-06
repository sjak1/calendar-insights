import asyncio
import json
import queue
import re
import threading
import time
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from query_processor import handle_query
from pydantic import BaseModel
import os
from logging_config import setup_logging, get_logger

# Setup logging for FastAPI
setup_logging()
logger = get_logger(__name__)

app = FastAPI()

# Mount static files directory
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


def _display_name_from_email(email: str) -> str:
    """Derive a human-friendly display name from an email address.

    supportuser@x.com   -> Support User
    john.doe@x.com      -> John Doe
    jane_smith@x.com    -> Jane Smith
    jdoe@x.com          -> Jdoe  (single token, just capitalise)
    """
    if not email or "@" not in email:
        return ""
    local = email.split("@")[0]
    # split on '.', '_', '-', or camelCase boundaries
    parts = re.split(r"[._\-]", local)
    if len(parts) == 1:
        # try camelCase split: "supportUser" -> ["support", "User"]
        parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", parts[0]).split()
    return " ".join(p.capitalize() for p in parts if p)


class QueryPayload(BaseModel):
    query: str
    headers: dict
    session_id: str = None  # Optional session ID for chat context


@app.get("/")
async def root():
    """Serve the UI"""
    logger.info("Root endpoint accessed")
    static_file = os.path.join(static_dir, "index.html")
    if os.path.exists(static_file):
        return FileResponse(static_file)
    return {
        "message": "BriefingIQ AI Assistant API",
        "endpoints": {"/process_query": "POST"},
    }


@app.post("/process_query")
async def process_query(payload: QueryPayload, request: Request):
    query = payload.query
    body_headers = payload.headers or {}
    session_id = payload.session_id

    # Extract HTTP headers from the request
    # FastAPI Request.headers is case-insensitive, but we'll normalize to lowercase
    # for easier lookup while preserving original case
    http_headers = {}
    for key, value in request.headers.items():
        # Store with both original case and lowercase for flexible lookup
        http_headers[key] = value
        http_headers[key.lower()] = value

    # Merge headers: body headers take precedence over HTTP headers
    headers = {**http_headers, **body_headers}

    # Debug: Log all headers received
    logger.info(f"📥 Received HTTP headers: {len(http_headers)} headers from request")
    logger.info(
        f"📥 Received body headers: {list(body_headers.keys()) if body_headers else 'None'}"
    )
    logger.info(f"📥 Merged headers: {list(headers.keys())[:10]}... (showing first 10)")
    if headers:
        # Log all header keys and values (truncate long values)
        for key, value in headers.items():
            if isinstance(value, str) and len(value) > 50:
                logger.info(f"   {key}: {value[:50]}... (truncated)")
            else:
                logger.info(f"   {key}: {value}")

    # Extract event_id from headers (for context-aware agenda generation)
    # Try multiple possible header key formats (case-insensitive)
    # Since we stored both original and lowercase, we can check both
    event_id = (
        headers.get("x-cloud-eventid")
        or headers.get("x-cloud-event-id")
        or headers.get("X-Cloud-Eventid")
        or headers.get("X-Cloud-Event-ID")
        or headers.get("eventid")
        or headers.get("event_id")
        or headers.get("EventId")
        or headers.get("Event-ID")
    )

    if event_id:
        logger.info(
            f"✅ Event ID found in header: {event_id} (will prioritize over LLM-extracted)"
        )
    else:
        logger.info(
            f"⚠️  No event_id in header, will rely on LLM-extracted or company_name"
        )
        logger.info(
            f"   Searched for: x-cloud-eventid, X-Cloud-Eventid, x-cloud-event-id, eventid, event_id"
        )

    # Extract category_id from headers (for category-level context: list of events in this category)
    category_id = (
        headers.get("x-cloud-categoryid")
        or headers.get("x-cloud-category-id")
        or headers.get("X-Cloud-Categoryid")
        or headers.get("category_id")
        or headers.get("categoryid")
    )
    if category_id:
        logger.info(
            f"✅ Category ID found in header: {category_id} (for category-level context when no event_id)"
        )
    else:
        logger.info(f"   No category_id in header")

    # Extract enriched context headers
    email = headers.get("x_cloud_user") or headers.get("x-cloud-user") or ""
    user_info = {
        "email": email,
        "display_name": _display_name_from_email(email),
        "client_timezone": headers.get("x-cloud-client-timezone")
        or headers.get("client-timezone"),
        "context_timezone": headers.get("x-cloud-context-timezone")
        or headers.get("context-timezone"),
        "requested_timezone": headers.get("x-cloud-requested-timezone")
        or headers.get("requested-timezone"),
    }

    if user_info["email"]:
        domain = (
            user_info["email"].split("@")[-1]
            if "@" in user_info["email"]
            else "unknown"
        )
        logger.info(
            f"✅ User context: {user_info['display_name']} ({domain}) | Timezone: {user_info.get('client_timezone', 'N/A')}"
        )

    # Extract customer context if available
    customer_id = headers.get("x-cloud-customerid") or headers.get(
        "x-cloud-customer-id"
    )
    if customer_id:
        logger.info(f"✅ Customer context: {customer_id[:20]}...")

    # Extract category type
    category_type_id = headers.get("x-cloud-categorytypeid") or headers.get(
        "x-cloud-category-type-id"
    )
    if category_type_id:
        logger.info(f"✅ Category type: {category_type_id}")

    logger.info(
        f"Processing query: {query[:100]}... (session_id: {session_id}, event_id: {event_id}, category_id: {category_id})"
    )
    try:
        result = handle_query(
            query,
            headers,
            session_id=session_id,
            event_id=event_id,
            category_id=category_id,
            user_info=user_info,
        )
        logger.info("Query processed successfully")
        return {"message": result, "session_id": session_id}
    except Exception as e:
        logger.error(f"Error processing query: {e}", exc_info=True)
        raise


@app.post("/process_query_stream")
async def process_query_stream(payload: QueryPayload, request: Request):
    """Server-Sent Events version of /process_query.

    Streams lifecycle events (llm_start/llm_end, tool_start/tool_end, query_end)
    as the query runs, so a client can render a live waterfall of where the
    time is being spent.
    """
    query = payload.query
    body_headers = payload.headers or {}
    session_id = payload.session_id

    http_headers = {}
    for key, value in request.headers.items():
        http_headers[key] = value
        http_headers[key.lower()] = value
    headers = {**http_headers, **body_headers}

    event_id = (
        headers.get("x-cloud-eventid")
        or headers.get("x-cloud-event-id")
        or headers.get("eventid")
        or headers.get("event_id")
    )
    category_id = (
        headers.get("x-cloud-categoryid")
        or headers.get("x-cloud-category-id")
        or headers.get("category_id")
    )
    email = headers.get("x_cloud_user") or headers.get("x-cloud-user") or ""
    user_info = {
        "email": email,
        "display_name": _display_name_from_email(email),
        "client_timezone": headers.get("x-cloud-client-timezone"),
        "context_timezone": headers.get("x-cloud-context-timezone"),
        "requested_timezone": headers.get("x-cloud-requested-timezone"),
    }

    event_queue: "queue.Queue" = queue.Queue()
    start_ts = time.time()
    _SENTINEL = object()

    def on_event(ev_type, data):
        event_queue.put({"type": ev_type, "t": round(time.time() - start_ts, 3), **data})

    def run_query():
        try:
            handle_query(
                query,
                headers,
                session_id=session_id,
                event_id=event_id,
                category_id=category_id,
                user_info=user_info,
                on_event=on_event,
            )
        except Exception as e:
            logger.error(f"stream query error: {e}", exc_info=True)
            event_queue.put({"type": "error", "t": round(time.time() - start_ts, 3), "error": str(e)})
        finally:
            event_queue.put(_SENTINEL)

    threading.Thread(target=run_query, daemon=True).start()

    async def event_stream():
        loop = asyncio.get_event_loop()
        while True:
            event = await loop.run_in_executor(None, event_queue.get)
            if event is _SENTINEL:
                yield "event: done\ndata: {}\n\n"
                return
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
