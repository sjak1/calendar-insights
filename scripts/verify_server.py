#!/usr/bin/env python3
"""
Generate an agenda and watch it being checked, side by side, as it happens.

The command-line runner answers "did this agenda hold up" after the fact. This
answers it while you look at the agenda: the sessions land on the left, and to
their right each property reports back with the deterministic call that settled
it. Same 22 properties as check_agenda_quality — this only puts a front end on
them, and never re-implements one.

Deliberately a separate process from api.py. Generation takes a minute or more
and this is a development tool; putting it on the deployed app would mean a
Lambda timeout and an endpoint nobody outside the team should reach.

    python scripts/verify_server.py
    open http://127.0.0.1:8077

Needs the VPN (OpenSearch, Oracle) and AWS credentials for Bedrock. Reads only.
"""

import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.check_agenda_quality import (  # noqa: E402
    CASES, build_run, find_agenda, presenter_names,
)
from tools.agenda_generator import generate_agenda  # noqa: E402

PAGE = Path(__file__).parent.parent / "static" / "agenda_verify.html"
app = FastAPI(title="Agenda verification")


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE.read_text()


@app.get("/events")
def events(q: str = "", limit: int = 12):
    """Events whose customer or name matches what was typed."""
    try:
        from opensearch_client import search
    except ImportError:
        return {"events": [], "error": "opensearch_client unavailable"}

    q = (q or "").strip()
    if not q:
        return {"events": []}
    body = {
        "size": limit,
        "query": {"bool": {"should": [
            {"match_phrase_prefix": {"customerName": q}},
            {"match_phrase_prefix": {"eventName": q}},
        ], "minimum_should_match": 1}},
        "_source": ["eventId", "eventName", "customerName", "duration", "startTime"],
        "sort": [{"startTime": {"order": "desc"}}],
    }
    try:
        res = search(index="events", body=body)
    except Exception as exc:
        return {"events": [], "error": str(exc)}

    out = []
    for hit in res.get("hits") or []:
        src = hit.get("source") or hit.get("_source") or {}
        out.append({
            "event_id": src.get("eventId"),
            "name": src.get("eventName"),
            "customer": src.get("customerName"),
            "days": src.get("duration") or 1,
            "start_ms": src.get("startTime"),
        })
    return {"events": [e for e in out if e["event_id"]]}


class VerifyPayload(BaseModel):
    event_id: str


@app.post("/verify")
def verify(payload: VerifyPayload):
    """Stream the agenda, then each property as it is decided."""
    channel: queue.Queue = queue.Queue()

    def work():
        try:
            channel.put({"stage": "generating", "event_id": payload.event_id})
            started = time.time()
            result = generate_agenda(event_id=payload.event_id, include_provenance=True)
            elapsed = time.time() - started
            result.pop("agenda_structured", None)   # pydantic object, not serialisable

            channel.put({
                "stage": "agenda",
                "elapsed": round(elapsed, 1),
                "success": bool(result.get("success")),
                "error": result.get("error"),
                "company": result.get("company"),
                "ebd_status": result.get("ebd_status"),
                "confidence": result.get("confidence"),
                "sessions": [{
                    "day": s.get("day"),
                    "time_slot": s.get("time_slot"),
                    "title": s.get("title"),
                    "presenter": s.get("presenter"),
                    "presenter_names": presenter_names(s),
                    "topic": s.get("topic"),
                    "format": s.get("format"),
                } for s in (result.get("sessions") or [])],
            })

            channel.put({"stage": "truth"})
            run = build_run(payload.event_id, result, elapsed)

            counts = {"pass": 0, "fail": 0, "skip": 0}
            for group, label, fn in CASES:
                run._current = label
                try:
                    verdict, detail = fn(run)
                except Exception as exc:
                    verdict, detail = False, f"raised {type(exc).__name__}: {exc}"
                counts["pass" if verdict is True else
                       "skip" if verdict is None else "fail"] += 1
                channel.put({
                    "stage": "check",
                    "group": group,
                    "label": label,
                    "verdict": verdict,
                    "detail": detail,
                    "evidence": run.evidence_for(label),
                })
            run._current = None
            channel.put({"stage": "done", "counts": counts})
        except Exception as exc:
            channel.put({"stage": "error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            channel.put(None)

    threading.Thread(target=work, daemon=True).start()

    def stream():
        while True:
            item = channel.get()
            if item is None:
                yield "event: done\ndata: {}\n\n"
                return
            yield f"data: {json.dumps(item, default=str)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    port = int(os.getenv("VERIFY_PORT", "8077"))
    print(f"\n  agenda verification  ->  http://127.0.0.1:{port}\n")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
