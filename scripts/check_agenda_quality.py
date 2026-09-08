#!/usr/bin/env python3
"""
Properties a generated agenda must hold, and a runner for them.

The unit suite mocks the model out, so it proves the scheduler and the window
maths are right and says nothing about what actually comes back from a real
run. This closes that half: it generates a real agenda against a real event and
then interrogates the result three ways.

  structure     every day covered, nothing overlapping, sessions inside the
                booked hours, counts inside the range the prompt asked for
  accuracy      the company, industry and attendee count match the event
                record; every topic is one the tenant actually has; every
                presenter is a real person from the pool, not invented
  availability  every assigned presenter is re-checked against the live
                calendar at the slot they ended up in, independently of the
                scheduler that placed them

Properties, not fixed outputs. An agenda is generated text: asserting exact
sessions would fail on every run and teach everyone to ignore the result. What
must hold regardless of wording is stated here, so a change that breaks the
intent fails loudly instead of producing a plausible-looking agenda nobody
checks.

Cases SKIP rather than fail when the evidence to judge them is absent — no
booked window on the event, no topic vocabulary for the tenant, no email for a
presenter. A skip means "not proven", never "fine".

Usage:
  python scripts/check_agenda_quality.py --event 12345
  python scripts/check_agenda_quality.py --event 12345 --repeat 6   # find the flake
  python scripts/check_agenda_quality.py --event 12345 --json out.json
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.agenda_generator import (  # noqa: E402
    _MAX_SESSIONS_TOTAL,
    _briefing_window,
    _event_num_days,
    _fetch_meeting_context,
    _parse_time_slot,
    _session_count_range,
    generate_agenda,
)

CASES = []


def case(group, label):
    def deco(fn):
        CASES.append((group, label, fn))
        return fn
    return deco


# ---------------------------------------------------------------------------
# One run: the agenda, plus the source data it should have been built from
# ---------------------------------------------------------------------------

class Run:
    def __init__(self, event_id, result, context, elapsed):
        self.event_id = event_id
        self.result = result
        self.context = context
        self.elapsed = elapsed
        self.meeting = (context or {}).get("meeting_details") or {}
        self.attendees = (context or {}).get("attendees") or []
        self.topics = [t for t in ((context or {}).get("available_topics") or []) if t]
        self.sessions = result.get("sessions") or []
        self.num_days = _event_num_days(self.meeting) or 1

    def by_day(self):
        days = defaultdict(list)
        for s in self.sessions:
            days[s.get("day") or 1].append(s)
        return days

    def window(self, day):
        """(start_ms, end_ms, tz) actually booked for this day, or (None, None, tz)."""
        try:
            return _briefing_window(self.meeting, day)
        except Exception:
            return None, None, None

    def slot_bounds_ms(self, session):
        """Absolute epoch-ms bounds of a session's final time slot, or None.

        Built from the day's booked window rather than the clock string alone,
        so the date and timezone come from the event and not from a guess.
        """
        parsed = _parse_time_slot(session.get("time_slot") or "")
        if not parsed:
            return None
        start_ms, _end_ms, tz = self.window(session.get("day") or 1)
        if not start_ms or tz is None:
            return None
        midnight = (datetime.fromtimestamp(start_ms / 1000, tz)
                    .replace(hour=0, minute=0, second=0, microsecond=0))
        s, e = parsed
        return (int((midnight + timedelta(minutes=s)).timestamp() * 1000),
                int((midnight + timedelta(minutes=e)).timestamp() * 1000))

    def emails(self):
        """presenter name (lowered) -> email, from the provenance candidate pool."""
        out = {}
        for entry in (self.result.get("provenance") or {}).get("sessions", []):
            for cand in entry.get("candidates") or []:
                name, email = cand.get("presenter_name"), cand.get("email")
                if name and email:
                    out[name.strip().lower()] = email.lower()
        for rec in self.result.get("presenter_recommendations") or []:
            name, email = rec.get("presenter_name"), rec.get("email")
            if name and email:
                out.setdefault(name.strip().lower(), email.lower())
        return out

    def known_people(self):
        """Every presenter name the source data offered, lowered."""
        names = set()
        for rec in self.result.get("presenter_recommendations") or []:
            for key in ("presenter_name", "chosen"):
                if rec.get(key):
                    names.add(rec[key].strip().lower())
            for cand in rec.get("candidates") or []:
                if cand.get("presenter_name"):
                    names.add(cand["presenter_name"].strip().lower())
        for entry in (self.result.get("provenance") or {}).get("sessions", []):
            for cand in entry.get("candidates") or []:
                if cand.get("presenter_name"):
                    names.add(cand["presenter_name"].strip().lower())
        for att in self.attendees:
            if att.get("name"):
                names.add(att["name"].strip().lower())
        return names


def presenter_names(session):
    """The people a session names, split out of the 'Name, Title' convention."""
    raw = (session.get("presenter") or "").strip()
    if not raw:
        return []
    out = []
    for part in raw.split(" and "):
        name = part.split(",")[0].split("(")[0].strip()
        if name and name.lower() not in {"tbd", "n/a", "team", "oracle team"}:
            out.append(name)
    return out


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

@case("structure", "the call succeeded")
def _ok(r):
    return bool(r.result.get("success")), r.result.get("error") or "ok"


@case("structure", "every day of the event carries at least one session")
def _all_days(r):
    if r.num_days <= 1:
        return None, "single-day event"
    days = set(r.by_day())
    missing = [d for d in range(1, r.num_days + 1) if d not in days]
    return not missing, f"{r.num_days} days, empty: {missing or 'none'}"


@case("structure", "no two sessions on a day overlap")
def _no_overlap(r):
    bad = []
    for day, sessions in r.by_day().items():
        spans = []
        for s in sessions:
            p = _parse_time_slot(s.get("time_slot") or "")
            if p:
                spans.append((p[0], p[1], s.get("title")))
        spans.sort()
        for (s1, e1, t1), (s2, e2, t2) in zip(spans, spans[1:]):
            if s2 < e1:
                bad.append(f"day{day}: {t1!r} ends {e1} but {t2!r} starts {s2}")
    return not bad, "; ".join(bad[:3]) or "clean"


@case("structure", "every session has a time slot")
def _slotted(r):
    missing = [s.get("title") for s in r.sessions if not (s.get("time_slot") or "").strip()]
    return not missing, f"{len(missing)} unslotted: {missing[:3]}"


@case("structure", "sessions sit inside the hours actually booked")
def _inside_window(r):
    outside, checked = [], 0
    for day, sessions in r.by_day().items():
        start_ms, end_ms, tz = r.window(day)
        if not start_ms or not end_ms:
            continue
        checked += 1
        lo = datetime.fromtimestamp(start_ms / 1000, tz)
        hi = datetime.fromtimestamp(end_ms / 1000, tz)
        lo_min, hi_min = lo.hour * 60 + lo.minute, hi.hour * 60 + hi.minute
        for s in sessions:
            p = _parse_time_slot(s.get("time_slot") or "")
            if p and (p[0] < lo_min or p[1] > hi_min):
                outside.append(f"day{day} {s.get('title')!r} {s.get('time_slot')} "
                               f"vs {lo:%H:%M}-{hi:%H:%M}")
    if not checked:
        return None, "no booked window on this event"
    return not outside, "; ".join(outside[:3]) or f"{checked} day windows honoured"


@case("structure", "sessions per day land inside the range the prompt asked for")
def _count_range(r):
    off, checked = [], 0
    for day, sessions in r.by_day().items():
        start_ms, end_ms, _tz = r.window(day)
        if not start_ms or not end_ms:
            continue
        checked += 1
        lo, hi = _session_count_range((end_ms - start_ms) // 60000, r.num_days)
        if not lo <= len(sessions) <= hi:
            off.append(f"day{day}: {len(sessions)} not in {lo}-{hi}")
    if not checked:
        return None, "no booked window to derive a range from"
    return not off, "; ".join(off) or "all days in range"


@case("structure", "the total respects the whole-briefing ceiling")
def _total_cap(r):
    n = len(r.sessions)
    return n <= _MAX_SESSIONS_TOTAL, f"{n} sessions vs cap {_MAX_SESSIONS_TOTAL}"


@case("structure", "session_count matches the sessions actually returned")
def _count_agrees(r):
    return r.result.get("session_count") == len(r.sessions), \
        f"reported {r.result.get('session_count')}, got {len(r.sessions)}"


@case("structure", "a full day includes a break over the middle of it")
def _lunch(r):
    missing, checked = [], 0
    for day, sessions in r.by_day().items():
        start_ms, end_ms, _tz = r.window(day)
        if not start_ms or not end_ms or (end_ms - start_ms) < 5 * 3600 * 1000:
            continue
        checked += 1
        words = ("lunch", "break", "refreshment", "networking")
        if not any(w in (s.get("title") or "").lower() for s in sessions for w in words):
            missing.append(day)
    if not checked:
        return None, "no full day booked"
    return not missing, f"days without a break: {missing or 'none'}"


# ---------------------------------------------------------------------------
# Accuracy — is the agenda describing the real event, or inventing one
# ---------------------------------------------------------------------------

@case("accuracy", "the company matches the event record")
def _company(r):
    truth = (r.meeting.get("company_name") or "").strip()
    if not truth:
        return None, "no company on the event record"
    got = (r.result.get("company") or "").strip()
    return got.lower() == truth.lower(), f"agenda {got!r} vs record {truth!r}"


@case("accuracy", "the industry matches the event record")
def _industry(r):
    truth = (r.meeting.get("industry") or "").strip()
    if not truth:
        return None, "no industry on the event record"
    got = (r.result.get("industry") or "").strip()
    return got.lower() == truth.lower(), f"agenda {got!r} vs record {truth!r}"


@case("accuracy", "the attendee count matches the attendee list")
def _attendee_count(r):
    if not r.attendees:
        return None, "no attendees on the event record"
    return r.result.get("attendee_count") == len(r.attendees), \
        f"agenda {r.result.get('attendee_count')} vs {len(r.attendees)} on record"


@case("accuracy", "every topic tag is one the tenant actually has")
def _topics_real(r):
    if not r.topics:
        return None, "no topic vocabulary for this tenant"
    allowed = {t.strip().lower() for t in r.topics}
    invented = sorted({(s.get("topic") or "").strip() for s in r.sessions
                       if s.get("topic") and s["topic"].strip().lower() not in allowed})
    return not invented, f"invented: {invented[:4]}" if invented else \
        f"{len({s.get('topic') for s in r.sessions if s.get('topic')})} tags, all real"


@case("accuracy", "every presenter is a real person from the source data")
def _presenters_real(r):
    known = r.known_people()
    if not known:
        return None, "no presenter pool to check against"
    invented = []
    for s in r.sessions:
        for name in presenter_names(s):
            if name.lower() not in known:
                invented.append(f"{name} ({s.get('title')})")
    return not invented, f"not in source data: {invented[:4]}" if invented else \
        f"{len(known)} known people, none invented"


@case("accuracy", "the header presenter list is drawn from the same pool")
def _header_presenters(r):
    known = r.known_people()
    listed = [p.get("name") for p in (r.result.get("presenters") or []) if p.get("name")]
    if not known or not listed:
        return None, "no pool or no header presenters"
    invented = [n for n in listed if n.strip().lower() not in known]
    return not invented, f"not in source data: {invented[:4]}" if invented else \
        f"{len(listed)} listed, all real"


@case("accuracy", "ebd_status is a real verdict and agrees with ebd_used")
def _ebd_status(r):
    status, used = r.result.get("ebd_status"), r.result.get("ebd_used")
    if status not in {"used", "none_found", "unusable"}:
        return False, f"unknown status {status!r}"
    return (status == "used") == bool(used), f"status={status} used={used}"


@case("accuracy", "a briefing built without a usable document records its assumptions")
def _assumptions(r):
    if r.result.get("ebd_status") == "used":
        return None, "the briefing document was usable"
    notes = (r.result.get("strategic_notes") or {}).get("assumptions") or []
    return bool(notes), f"{len(notes)} assumptions recorded"


# ---------------------------------------------------------------------------
# Availability — re-checked against the calendar, not taken on trust
# ---------------------------------------------------------------------------

@case("availability", "no day was scheduled without an availability check")
def _all_days_checked(r):
    avail = r.result.get("availability") or {}
    unchecked = avail.get("days_without_availability_check")
    if unchecked is None:
        return None, "no availability summary on the result"
    return not unchecked, f"unchecked days: {unchecked or 'none'}"


@case("availability", "every assigned presenter is genuinely free at their slot")
def _presenters_free(r):
    from tools.presenter_suggest import _check_presenter_conflicts

    emails = r.emails()
    if not emails:
        return None, "no presenter emails available (run with provenance)"

    busy, checked = [], 0
    for s in r.sessions:
        bounds = r.slot_bounds_ms(s)
        if not bounds:
            continue
        for name in presenter_names(s):
            email = emails.get(name.lower())
            if not email:
                continue
            checked += 1
            conflicts = _check_presenter_conflicts(
                [email], bounds[0], bounds[1], exclude_event_id=str(r.event_id)
            )
            for hit in conflicts.get(email, []):
                busy.append(f"{name} at {s.get('time_slot')} day{s.get('day')} "
                            f"— {hit.get('event_name')}")
    if not checked:
        return None, "no slot/email pair resolvable"
    return not busy, "; ".join(busy[:3]) or f"{checked} assignments re-checked, all free"


@case("availability", "every backup presenter is free at the slot they back up")
def _backups_free(r):
    from tools.presenter_suggest import _check_presenter_conflicts

    emails = r.emails()
    if not emails:
        return None, "no presenter emails available"
    busy, checked = [], 0
    for s in r.sessions:
        bounds = r.slot_bounds_ms(s)
        if not bounds:
            continue
        for backup in s.get("backup_presenters") or []:
            email = emails.get((backup.get("presenter_name") or "").strip().lower())
            if not email:
                continue
            checked += 1
            if _check_presenter_conflicts([email], bounds[0], bounds[1],
                                          exclude_event_id=str(r.event_id)).get(email):
                busy.append(f"{backup.get('presenter_name')} @ {s.get('time_slot')}")
    if not checked:
        return None, "no backups carrying a resolvable email"
    return not busy, "; ".join(busy[:3]) or f"{checked} backups re-checked, all free"


@case("availability", "every topic-matched presenter says why they were picked")
def _reasons(r):
    matched = [s for s in r.sessions if s.get("topic_presenter_suggestion")]
    if not matched:
        return None, "no per-session presenter matches on this agenda"
    silent = [s.get("title") for s in matched
              if not (s["topic_presenter_suggestion"] or {}).get("reason")]
    return not silent, f"{len(silent)} without a reason: {silent[:3]}"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def do_run(event_id):
    started = time.time()
    result = generate_agenda(event_id=str(event_id), include_provenance=True)
    elapsed = time.time() - started
    try:
        context = _fetch_meeting_context(event_id=str(event_id))
        try:
            from tools.presenter_suggest import _available_topics, ACTIVITIES_INDEX
            context["available_topics"] = _available_topics(ACTIVITIES_INDEX, limit=150)
        except Exception:
            context["available_topics"] = []
    except Exception as exc:
        print(f"  ! could not fetch ground truth: {exc}")
        context = {}
    return Run(event_id, result, context, elapsed)


def judge(run):
    rows = []
    for group, label, fn in CASES:
        try:
            verdict, detail = fn(run)
        except Exception as exc:
            verdict, detail = False, f"raised {type(exc).__name__}: {exc}"
        rows.append((group, label, verdict, detail))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Property checks on a generated agenda.")
    ap.add_argument("--event", required=True, help="event id to generate against")
    ap.add_argument("--repeat", type=int, default=1,
                    help="generate N times; agenda generation is stochastic and "
                         "some failures only show up across runs")
    ap.add_argument("--json", metavar="PATH", help="write the full results here")
    args = ap.parse_args()

    all_rows, runs = [], []
    for i in range(args.repeat):
        print(f"\n=== run {i + 1}/{args.repeat} — event {args.event} ===")
        run = do_run(args.event)
        rows = judge(run)
        runs.append(run)
        all_rows.append(rows)

        days = sorted(run.by_day())
        print(f"  {len(run.sessions)} sessions over days {days} in {run.elapsed:.1f}s "
              f"· ebd={run.result.get('ebd_status')} "
              f"· confidence={run.result.get('confidence')}")
        group = None
        for g, label, verdict, detail in rows:
            if g != group:
                print(f"\n  [{g}]")
                group = g
            mark = "PASS" if verdict else ("SKIP" if verdict is None else "FAIL")
            print(f"    {mark}  {label}")
            if verdict is not True:
                print(f"            {detail}")

    print("\n" + "=" * 70)
    if args.repeat > 1:
        print(f"across {args.repeat} runs:")
        for idx, (group, label, _fn) in enumerate(CASES):
            verdicts = [rows[idx][2] for rows in all_rows]
            fails = sum(1 for v in verdicts if v is False)
            skips = sum(1 for v in verdicts if v is None)
            if fails or skips:
                bits = []
                if fails:
                    bits.append(f"{fails} failed")
                if skips:
                    bits.append(f"{skips} skipped")
                print(f"  {label}\n      {', '.join(bits)} of {args.repeat}")
        if not any(v is False for rows in all_rows for _g, _l, v, _d in rows):
            print("  every property held on every run")

    total_fail = sum(1 for rows in all_rows for _g, _l, v, _d in rows if v is False)
    total_pass = sum(1 for rows in all_rows for _g, _l, v, _d in rows if v is True)
    total_skip = sum(1 for rows in all_rows for _g, _l, v, _d in rows if v is None)
    print(f"\n{total_pass} passed, {total_fail} failed, {total_skip} skipped "
          f"({len(CASES)} properties x {args.repeat} runs)")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump([{"event": r.event_id, "elapsed": r.elapsed,
                        "sessions": len(r.sessions), "days": sorted(r.by_day()),
                        "checks": [{"group": g, "label": l, "verdict": v, "detail": d}
                                   for g, l, v, d in rows]}
                       for r, rows in zip(runs, all_rows)], fh, indent=2)
        print(f"wrote {args.json}")

    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(main())
