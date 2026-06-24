"""
Agent eval: 20 real queries with ground-truth checks, run against the live
/process_query endpoint. Ground truth pulled from OpenSearch on 2026-06-11.

Usage:
    python eval_agent.py <label>            # e.g. python eval_agent.py sonnet
    python eval_agent.py <label> --base http://127.0.0.1:8000

Set the model via BEDROCK_MODEL_ID in .env (server restarts on reload).
Results: /tmp/eval_<label>.json + summary on stdout.
"""

import argparse
import json
import re
import sys
import time

import requests

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def D(mon: str, day: int, year: int) -> str:
    """Regex matching a date in common formats: 'Dec 10, 2026', 'December 10 2026',
    '10 December 2026', '2026-12-10', '12/10/2026'."""
    m = _MONTHS[mon]
    return (
        rf"(?:{mon}\w*[ .]*0?{day}(?:st|nd|rd|th)?,?\s+{year}"
        rf"|0?{day}(?:st|nd|rd|th)?\s+{mon}\w*,?\s+{year}"
        rf"|{year}-{m:02d}-{day:02d}"
        rf"|0?{m}/0?{day}/{year})"
    )


# (id, query, {"all": [...], "any": [...], "none": [...]})
CASES = [
    ("honda_date", "When is the Honda Motor event and what is its status?",
     {"all": [D("dec", 10, 2026), r"waitlist"], "none": [r"\b2027\b"]}),
    ("apple_count", "How many Apple events do we have in total?",
     {"any": [r"\b3\b", r"\bthree\b"]}),
    ("apple_dates", "List all Apple events with their dates",
     {"all": [D("dec", 1, 2026), D("dec", 9, 2026), D("dec", 15, 2026)],
      "none": [r"\b2027\b"]}),
    ("apple_submitted", "Which Apple event is in Submitted status? Give its event ID and date.",
     {"any": [r"CBR-20261215-081", D("dec", 15, 2026)]}),
    ("google_earliest", "What is the earliest scheduled Google event? Give me the date.",
     {"all": [D("aug", 6, 2026)], "none": [r"\b2027\b"]}),
    ("ms_dec10_count", "How many Microsoft events are scheduled on December 10, 2026?",
     {"any": [r"\b2\b", r"\btwo\b"]}),
    ("ba_count", "How many British Airways events are there?",
     {"any": [r"\b2\b", r"\btwo\b"]}),
    ("dt_austin", "When is the Deutsche Telekom event in Austin and what's its status?",
     {"all": [D("dec", 10, 2026), r"waitlist"], "none": [r"\b2027\b"]}),
    ("grafana_nashville", "What is the status of the Grafana Labs event in Nashville?",
     {"all": [r"waitlist"]}),
    ("bentley_confirmed", "Which Bentley event is Confirmed and at which location?",
     {"all": [r"austin"]}),
    ("confirmed_count", "How many events are in Confirmed status overall?",
     {"any": [r"\b21\b", r"\btwenty[- ]one\b"]}),
    ("hold_count", "How many events are currently in Hold status?",
     {"any": [r"\b35\b", r"\bthirty[- ]five\b"]}),
    ("austin_count", "How many events are at Austin, TX?",
     {"any": [r"\b5\b", r"\bfive\b"]}),
    ("top_location", "Which location hosts the most events?",
     {"all": [r"redwood\s+shores"]}),
    ("waitlist_count", "How many events are in Waitlist status?",
     {"any": [r"\b19\b", r"\bnineteen\b"]}),
    ("amazon_june", "When is the Amazon event in June 2026?",
     {"all": [D("jun", 8, 2026)], "none": [r"\b2027\b"]}),
    ("freshworks_dates", "When are the two Freshworks events scheduled?",
     {"all": [D("dec", 10, 2026), D("dec", 14, 2026)], "none": [r"\b2027\b"]}),
    ("declined_count", "How many events have been Declined?",
     {"any": [r"\b2\b", r"\btwo\b"]}),
    ("ms_aug", "When is the Microsoft event in August 2026?",
     {"all": [D("aug", 10, 2026)], "none": [r"\b2027\b"]}),
    ("gap_count", "How many Gap events do we have?",
     {"any": [r"\b3\b", r"\bthree\b"]}),
]


def check(text: str, checks: dict):
    """Return (passed, failures). Case-insensitive regex matching."""
    failures = []
    for pat in checks.get("all", []):
        if not re.search(pat, text, re.IGNORECASE):
            failures.append(f"missing required: {pat}")
    any_pats = checks.get("any", [])
    if any_pats and not any(re.search(p, text, re.IGNORECASE) for p in any_pats):
        failures.append(f"none of expected matched: {any_pats}")
    for pat in checks.get("none", []):
        if re.search(pat, text, re.IGNORECASE):
            failures.append(f"forbidden match: {pat}")
    return (not failures), failures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("label")
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    args = ap.parse_args()

    results = []
    n_pass = 0
    model_seen = ""
    for cid, query, checks in CASES:
        t0 = time.time()
        try:
            r = requests.post(
                f"{args.base}/process_query",
                json={"query": query, "headers": {}},
                timeout=120,
            )
            msg = r.json()["message"]
            text = msg.get("text", "")
            model_seen = msg.get("model", model_seen)
            tokens_in = msg.get("tokens_in", 0)
            tokens_out = msg.get("tokens_out", 0)
        except Exception as e:
            text = f"<ERROR: {e}>"
            tokens_in = tokens_out = 0
        elapsed = time.time() - t0
        passed, failures = check(text, checks)
        n_pass += passed
        results.append({
            "id": cid, "query": query, "passed": passed, "failures": failures,
            "elapsed_s": round(elapsed, 2), "tokens_in": tokens_in,
            "tokens_out": tokens_out, "text": text,
        })
        print(f"{'PASS' if passed else 'FAIL':4s} {cid:20s} {elapsed:6.1f}s"
              + ("" if passed else f"  -> {failures}"), flush=True)
        time.sleep(1)

    avg_t = sum(r["elapsed_s"] for r in results) / len(results)
    total_in = sum(r["tokens_in"] for r in results)
    total_out = sum(r["tokens_out"] for r in results)
    summary = {
        "label": args.label, "model": model_seen,
        "passed": n_pass, "total": len(CASES),
        "avg_latency_s": round(avg_t, 2),
        "tokens_in": total_in, "tokens_out": total_out,
    }
    out_path = f"/tmp/eval_{args.label}.json"
    with open(out_path, "w") as f:
        json.dump({"summary": summary, "results": results}, f, indent=2)
    print(f"\n== {args.label} ({model_seen}): {n_pass}/{len(CASES)} passed | "
          f"avg {avg_t:.1f}s | tokens in/out {total_in}/{total_out}")
    print(f"details: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
