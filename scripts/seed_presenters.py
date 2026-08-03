"""Seed a small, deliberately-shaped presenter/topic set into the activities index.

The live data has 5 presenters across 1091 topics, so every topic query returns
the same five people and there is no way to tell a good ranker from a bad one.
This seeds 20 activities built as *named test cases* (specialist vs generalist,
exact vs token match, high vs low acceptance, a calendar conflict) so retrieval
and ranking changes have something to be measured against.

Every doc gets an explicit _id of SEED-ACT-NNN and every presenter an
@seed.example address, so cleanup is exact and the rows are obvious on sight.
No new field paths are introduced — the docs mirror the existing shape, so the
index mapping is untouched.

Usage:
  python scripts/seed_presenters.py            # dry run, prints what it would write
  python scripts/seed_presenters.py --apply    # write to the activities index
  python scripts/seed_presenters.py --delete   # remove exactly what this wrote
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

INDEX = "activities"
ID_PREFIX = "SEED-ACT-"
EMAIL_DOMAIN = "seed.example"
TZ = "America/Los_Angeles"

# ---------------------------------------------------------------- presenters
# (key, first, last, title) — designation drives the seniority tier regex
PRESENTERS = {
    "priya":  ("Priya",  "Raman",    "Director, Database Engineering"),
    "ana":    ("Ana",    "Silva",    "Principal Solution Architect"),
    "marcus": ("Marcus", "Webb",     "Senior Solution Engineer"),
    "tom":    ("Tom",    "Nakamura", "Principal Cloud Architect"),
    "grace":  ("Grace",  "Okafor",   "Head of Risk Analytics"),
    "dan":    ("Dan",    "Foley",    "Solution Engineer"),
    "leila":  ("Leila",  "Hassan",   "Industry Director, Hospitality"),
    "raj":    ("Raj",    "Menon",    "SVP, Cloud Platform"),
}

# ------------------------------------------------------------------ activities
# (day_offset, hour, topic, [(presenter_key, status), ...], event_key)
#
# Test cases encoded below:
#   A. Priya = specialist, 6 sessions all on "Autonomous Database", 5 accepted
#   B. Ana   = same exact topic but only 3 sessions, all more recent than Priya's
#            -> tests depth-vs-recency; today recency wins by accident
#   C. Marcus= generalist, 5 sessions 5 different topics
#            -> should lose an exact-topic query, win on breadth
#   D. Tom   = 5 sessions but 4 declined -> only 1 should survive the filter
#   E. Grace = sole owner of "Quantum Risk Modeling" -> "only exact match" case
#   F. Dan   = two activities at the SAME hour -> availability conflict
#   G. Leila = "Cloud Kitchen Operations" -> token trap: matches "cloud",
#            semantically unrelated. An exact-first ranker must demote her.
#   H. Raj   = SVP title -> audience_level=vp_plus / c_level probe
ACTIVITIES = [
    # A — Priya, specialist (oldest block)
    (-90, 9,  "Autonomous Database",            [("priya", "Accepted")], "e1"),
    (-84, 11, "Autonomous Database",            [("priya", "Accepted"), ("marcus", "Accepted")], "e1"),
    (-77, 14, "Autonomous Database",            [("priya", "Accepted")], "e2"),
    (-70, 10, "Autonomous Database",            [("priya", "Declined")], "e2"),
    (-63, 15, "Autonomous Database",            [("priya", "Accepted")], "e3"),
    (-56, 9,  "Autonomous Database",            [("priya", "Accepted"), ("raj", "Accepted")], "e3"),

    # B — Ana, same topic, fewer but newer
    (-14, 10, "Autonomous Database",            [("ana", "Accepted")], "e1"),
    (-9,  13, "Autonomous Database",            [("ana", "Accepted")], "e2"),
    (-4,  11, "Autonomous Database",            [("ana", "Pending")],  "e3"),

    # C — Marcus, generalist
    (-49, 10, "Exadata Cloud Service",          [("marcus", "Accepted")], "e2"),
    (-42, 14, "GoldenGate Replication",         [("marcus", "Accepted")], "e3"),
    (-35, 9,  "APEX Low Code",                  [("marcus", "Pending")],  "e1"),
    (-28, 16, "Observability and Management",   [("marcus", "Accepted")], "e2"),

    # D — Tom, high volume / low acceptance
    (-60, 9,  "Autonomous Database Migration",  [("tom", "Declined")], "e1"),
    (-53, 11, "Autonomous Database Migration",  [("tom", "Declined")], "e2"),
    (-46, 13, "Autonomous Database Migration",  [("tom", "Accepted")], "e3"),
    (-39, 15, "Autonomous Database Migration",  [("tom", "Declined")], "e1"),

    # E — Grace, sole owner of a unique topic
    (-21, 10, "Quantum Risk Modeling",          [("grace", "Accepted")], "e2"),

    # F — Dan, deliberate same-hour double booking (both on day -7 at 14:00)
    (-7,  14, "Fusion Analytics Warehouse",     [("dan", "Accepted")], "e1"),
    (-7,  14, "Cloud Kitchen Operations",       [("dan", "Accepted"), ("leila", "Accepted")], "e3"),
]

EVENTS = {"e1": "SEED-EVT-001", "e2": "SEED-EVT-002", "e3": "SEED-EVT-003"}


def _presenter_obj(key: str) -> dict:
    first, last, title = PRESENTERS[key]
    email = f"{key}@{EMAIL_DOMAIN}"
    full = f"{first} {last}"
    return {
        "firstName": first,
        "lastName": last,
        "presenterName": full,
        "primaryEmail": email,
        "designation": title,
        "baseTimezone": TZ,
        "isActive": True,
        "isGlobal": True,
        "isExecutive": "false",
        "isEbdRequired": False,
        "isEmailOptOut": False,
        "textField1": first,
        "textField2": last,
        "textField4": email,
        "textField5": title,
        "textField8": full,
    }


def _time_block(day_offset: int, hour: int) -> tuple:
    """Return (startTime, endTime) blocks 60 minutes apart, anchored to today."""
    base = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) + timedelta(days=day_offset)
    start = base.replace(hour=hour)
    end = start + timedelta(hours=1)

    def block(dt: datetime) -> dict:
        iso = dt.strftime("%Y-%m-%dT%H:%M:%S")
        return {
            "utcMs": int(dt.timestamp() * 1000),
            "zoneId": TZ,
            "zoneTime": dt.strftime("%H:%M"),
            "requested": {"requestedZoneId": TZ, "requestedZoneDate": iso},
            "context": {
                "contextZoneId": TZ,
                "contextZoneDate": iso,
                "gmtDate": iso,
                "contextZoneTime": dt.strftime("%H:%M:%S"),
            },
        }

    return block(start), block(end)


def build_docs() -> list:
    docs = []
    for i, (day_offset, hour, topic, presenters, event_key) in enumerate(ACTIVITIES, 1):
        doc_id = f"{ID_PREFIX}{i:03d}"
        event_id = EVENTS[event_key]
        start, end = _time_block(day_offset, hour)

        topic_entry = {
            "activityId": doc_id,
            "eventId": event_id,
            "slotId": doc_id,
            "formTypeId": "topic",
            "topic": {"textField1": topic, "textField2": topic, "isActive": True},
            "textField2": {"textField1": topic, "textField2": topic, "isActive": True},
            "topicObjective": f"Seeded test case — {topic}",
        }

        presenter_entries = []
        for order, (key, status) in enumerate(presenters):
            first, last, title = PRESENTERS[key]
            presenter_entries.append({
                "activityId": doc_id,
                "eventId": event_id,
                "slotId": doc_id,
                "formTypeId": "topic_presenter",
                "presenter": _presenter_obj(key),
                "presenterEmail": f"{key}@{EMAIL_DOMAIN}",
                "presenterTitle": title,
                "presenterStatus": status,
                "presenterSortOrder": order,
                "sortOrder": order,
                "textField1": status,
                "textField2": f"{key}@{EMAIL_DOMAIN}",
                "textField3": title,
            })

        docs.append((doc_id, {
            "activityId": doc_id,
            "eventId": event_id,
            "bookingId": f"{event_id}-{i:03d}",
            "activityType": "Topic",
            "duration": 60,
            "startTime": start,
            "endTime": end,
            "status": {"stateName": "Confirmed", "displayText": "Confirmed"},
            "metadata": {
                "displayText5": "Topic",
                "title": f"Seeded test case — {topic}",
                "presenters": [
                    {"presenterName": f"{PRESENTERS[k][0]} {PRESENTERS[k][1]}",
                     "status": s, "sortOrder": n}
                    for n, (k, s) in enumerate(presenters)
                ],
            },
            "activityData": {
                "topic": [topic_entry],
                "topic_presenter": presenter_entries,
            },
        }))
    return docs


def _client():
    from opensearchpy import OpenSearch
    url = os.environ["OPENSEARCH_URL"]
    return OpenSearch(
        hosts=[url],
        http_auth=(os.environ["OPENSEARCH_USERNAME"], os.environ["OPENSEARCH_PASSWORD"]),
        verify_certs=os.getenv("OPENSEARCH_VERIFY_CERTS", "false").lower() in ("true", "1", "yes"),
        ssl_show_warn=False,
        timeout=60,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the docs to OpenSearch")
    ap.add_argument("--delete", action="store_true", help="delete exactly the docs this seeds")
    args = ap.parse_args()

    docs = build_docs()

    if args.delete:
        c = _client()
        gone = 0
        for doc_id, _ in docs:
            try:
                c.delete(index=INDEX, id=doc_id, refresh=True)
                gone += 1
            except Exception as e:
                if "not_found" not in str(e).lower():
                    print(f"  ! {doc_id}: {str(e)[:120]}")
        print(f"deleted {gone}/{len(docs)} seeded docs from '{INDEX}'")
        return

    if not args.apply:
        print(f"DRY RUN — {len(docs)} docs would be written to '{INDEX}'\n")
        by_presenter: dict = {}
        for _, d in docs:
            for p in d["activityData"]["topic_presenter"]:
                k = p["presenter"]["primaryEmail"]
                by_presenter.setdefault(k, []).append(
                    (d["activityData"]["topic"][0]["topic"]["textField1"], p["presenterStatus"])
                )
        for email, rows in sorted(by_presenter.items()):
            acc = sum(1 for _, s in rows if s == "Accepted")
            topics = sorted({t for t, _ in rows})
            print(f"  {email:<22} {len(rows)} sessions, {acc} accepted, {len(topics)} topic(s)")
            for t in topics:
                print(f"      · {t}")
        print(f"\n  ids: {docs[0][0]} … {docs[-1][0]}")
        print("  re-run with --apply to write, --delete to remove")
        return

    c = _client()
    ok = 0
    for doc_id, body in docs:
        c.index(index=INDEX, id=doc_id, body=body, refresh=False)
        ok += 1
    c.indices.refresh(index=INDEX)
    print(f"indexed {ok}/{len(docs)} docs into '{INDEX}' (ids {ID_PREFIX}001…{ID_PREFIX}{len(docs):03d})")


if __name__ == "__main__":
    main()
