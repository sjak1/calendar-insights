"""Put opportunity-revenue figures on existing events so ranking work has data.

The revenue fields exist and are mapped, but every value in the index is 0.0,
so there is nothing to test a revenue signal against. This writes a spread of
realistic figures — increases, decreases, one flat, one closed-lost, one with
no baseline — across the events that actually have presenter activity.

Only the three totals under eventFormData.EVENTS_VISIT_INFO[0] are touched.
Prior values are written to scripts/.opp_revenue_backup.json first, so --revert
restores exactly what was there. No new field paths, so the mapping is untouched.

Usage:
  python scripts/seed_opp_revenue.py            # dry run
  python scripts/seed_opp_revenue.py --apply
  python scripts/seed_opp_revenue.py --revert
"""

import argparse
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

INDEX = "events"
SECTION = "EVENTS_VISIT_INFO"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".opp_revenue_backup.json")

F_INITIAL = "totalInitialOppRevenue"
F_OPEN = "totalOppRevenue"
F_CLOSED = "totalClosedOppRevenue"

# eventId -> (initial, open, closed). Mirrors the dummy set discussed:
# 3 grew, 3 shrank, 1 flat, 1 closed-lost, 1 with no baseline.
#
# open vs closed is exclusive — a deal is either still running or finished —
# because the delta is computed as (closed or open) - initial. Setting both
# would make it ambiguous which one the change refers to.
SCENARIOS = {
    # eventId                                 initial     open      closed   label
    "3238AEE1-AB24-4032-AACD-4016C2B61E4B": (450000.0, None, 720000.0),      # Nikon        grew, closed
    "7DD68FB4-C967-42EE-B829-E30BD02763F2": (1200000.0, None, 900000.0),     # HCA          shrank, closed
    "96AF48FC-1647-4AD1-82CB-7A5030594158": (300000.0, 480000.0, None),      # Lamborghini  grew, open
    "3A5195AE-0598-449D-98E9-2C3E172E45D1": (850000.0, 640000.0, None),      # Alaska       shrank, open
    "A5566AA4-39C2-4A92-83D9-25470EBB78F7": (200000.0, None, 200000.0),      # Visa         flat
    "448105F4-275C-4F58-953C-46715A300FF4": (5000000.0, None, 6750000.0),    # Kansai       grew big, closed
    "C07DD837-6DD7-414B-8C96-EBB0B69CB7DC": (None, 350000.0, None),          # Reassign     no baseline
    "08714A78-9D5B-4E3B-88DC-76FF2DEB9735": (2500000.0, None, 0.0),          # Test Request closed-lost
}


def _client():
    from opensearchpy import OpenSearch

    return OpenSearch(
        hosts=[os.environ["OPENSEARCH_URL"]],
        http_auth=(os.environ["OPENSEARCH_USERNAME"], os.environ["OPENSEARCH_PASSWORD"]),
        verify_certs=os.getenv("OPENSEARCH_VERIFY_CERTS", "false").lower() in ("true", "1", "yes"),
        ssl_show_warn=False,
        timeout=60,
    )


def _section(doc):
    """The EVENTS_VISIT_INFO list on a doc, normalised to a list."""
    efd = doc.get("eventFormData") or {}
    sec = efd.get(SECTION)
    if sec is None:
        return None
    return sec if isinstance(sec, list) else [sec]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--revert", action="store_true")
    args = ap.parse_args()

    if args.revert:
        if not os.path.exists(BACKUP):
            print(f"no backup at {BACKUP} — nothing to revert")
            return
        c = _client()
        saved = json.load(open(BACKUP))
        for eid, section in saved.items():
            c.update(index=INDEX, id=eid,
                     body={"doc": {"eventFormData": {SECTION: section}}}, refresh=False)
            print(f"  reverted {eid}")
        c.indices.refresh(index=INDEX)
        print(f"reverted {len(saved)} events")
        return

    c = _client()
    backup, planned = {}, []

    for eid, (initial, open_, closed) in SCENARIOS.items():
        try:
            doc = c.get(index=INDEX, id=eid)["_source"]
        except Exception as e:
            print(f"  ! {eid}: {str(e)[:90]}")
            continue
        sec = _section(doc)
        if not sec:
            print(f"  ! {eid}: no {SECTION} section, skipping")
            continue

        backup[eid] = json.loads(json.dumps(sec))  # deep copy of the original
        updated = json.loads(json.dumps(sec))
        updated[0][F_INITIAL] = initial
        updated[0][F_OPEN] = open_
        updated[0][F_CLOSED] = closed

        latest = closed if closed is not None else open_
        delta = None if latest is None else latest - (initial or 0.0)
        planned.append((eid, doc.get("eventName"), initial, open_, closed, delta, updated))

    print(f"{'event':<24} {'initial':>11} {'open':>11} {'closed':>11} {'delta':>12}")
    for _, name, i, o, cl, d, _u in planned:
        fmt = lambda v: "—" if v is None else f"{v:,.0f}"
        print(f"{str(name)[:23]:<24} {fmt(i):>11} {fmt(o):>11} {fmt(cl):>11} {fmt(d):>12}")

    if not args.apply:
        print(f"\nDRY RUN — {len(planned)} events would be updated. Re-run with --apply.")
        return

    # Never overwrite an existing backup. The source system re-indexes these
    # docs, so a second run would otherwise capture our own figures as the
    # "originals" and make --revert restore the seed instead of the real values.
    if os.path.exists(BACKUP):
        print(f"\nbackup already exists at {BACKUP} — keeping the original one")
    else:
        json.dump(backup, open(BACKUP, "w"), indent=1)
        print(f"\noriginals saved to {BACKUP}")
    for eid, _n, _i, _o, _c, _d, updated in planned:
        c.update(index=INDEX, id=eid,
                 body={"doc": {"eventFormData": {SECTION: updated}}}, refresh=False)
    c.indices.refresh(index=INDEX)
    print(f"updated {len(planned)} events (--revert restores them)")


if __name__ == "__main__":
    main()
