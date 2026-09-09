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
from pathlib import Path

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

def _brief(value, limit=220):
    """Render a call's return value small enough to sit in a table cell."""
    if isinstance(value, dict):
        if not value:
            return "{}"
        body = ", ".join(f"{k}: {_brief(v, 60)}" for k, v in list(value.items())[:6])
        more = f", +{len(value) - 6} more" if len(value) > 6 else ""
        text = "{" + body + more + "}"
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
        if not items:
            return "[]"
        body = ", ".join(_brief(v, 40) for v in items[:8])
        more = f", +{len(items) - 8} more" if len(items) > 8 else ""
        text = "[" + body + more + "]"
    else:
        text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


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
        self._pool_cache = None
        self._wider_cache = None
        # Every deterministic call this run makes to establish truth, in order,
        # so the report can show the check beside the call that settled it
        # rather than asking anyone to take a verdict on faith.
        self.calls = []
        self._current = None
        self.meeting = (context or {}).get("meeting_details") or {}
        self.attendees = (context or {}).get("attendees") or []
        self.topics = [t for t in ((context or {}).get("available_topics") or []) if t]
        self.sessions = result.get("sessions") or []
        self.num_days = _event_num_days(self.meeting) or 1

    def record(self, call, output, *, note=""):
        """Log one truth-establishing call and what it returned."""
        self.calls.append({
            "check": self._current,
            "call": call,
            "output": output if isinstance(output, str) else _brief(output),
            "note": note,
        })

    def evidence_for(self, check):
        return [c for c in self.calls if c["check"] == check]

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
        """presenter name (lowered) -> email.

        Three sources, because none is reliable alone: the provenance
        candidates carry an address but come back empty whenever no pool was
        gathered for a session, and presenter_recommendations identifies people
        by presenter_id and drops the address entirely. The ranked pool is
        therefore queried directly as the fallback — the same source the agenda
        drew from, so the lookup stays independent of the scheduler's own
        bookkeeping without inventing a new notion of who these people are.
        """
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
        for person in self._pool():
            name = (person.get("presenter_name") or "").strip().lower()
            email = person.get("email") or next(iter(person.get("all_emails") or []), "")
            if name and email:
                out.setdefault(name, email.lower())
        return out

    def wider_topics(self):
        """Every topic in the index, well past what the prompt is shown.

        Only used to tell an invented tag from a reworded real one; never to
        widen what counts as copied.
        """
        if getattr(self, "_wider_cache", None) is None:
            try:
                from tools.presenter_suggest import _available_topics, ACTIVITIES_INDEX
                self._wider_cache = _available_topics(ACTIVITIES_INDEX, limit=2000)
            except Exception:
                self._wider_cache = []
        return self._wider_cache

    def _pool(self):
        """The ranked presenter pool for this event, fetched once and cached."""
        if getattr(self, "_pool_cache", None) is None:
            try:
                from tools.presenter_suggest import get_suggested_presenters
                res = get_suggested_presenters(event_id=str(self.event_id), limit=100)
                self._pool_cache = res.get("suggested_presenters") or []
            except Exception:
                self._pool_cache = []
        return self._pool_cache

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
        for person in self._pool():
            if person.get("presenter_name"):
                names.add(person["presenter_name"].strip().lower())
        # Per-session topic matching queries the index topic by topic, which
        # reaches people the event-scoped pool never contained. Those names come
        # from the ranking engine reading real activity records, not from the
        # model, so they are evidence rather than the claim under test.
        for entry in (self.result.get("topic_presenter_matching") or {}).get("rationale", []):
            if entry.get("chosen"):
                names.add(entry["chosen"].strip().lower())
            for runner in entry.get("runners_up") or []:
                if runner.get("presenter_name"):
                    names.add(runner["presenter_name"].strip().lower())
        return names

    def unverified_sessions(self):
        """Sessions whose presenter the ranking never got to check.

        provenance records these as "model choice, no topic to check against":
        the session carried no topic, so nothing looked the person up and the
        name is whatever the model wrote.
        """
        out = []
        for entry in (self.result.get("provenance") or {}).get("sessions", []):
            if "model choice" in (entry.get("presenter_source") or ""):
                out.append(entry)
        return out


# The presenter field is free text and the model varies the separator between
# name and title run to run: a comma, an em or en dash, a spaced hyphen, or a
# parenthesis. Splitting on only one of them leaves the title attached to the
# name, and every comparison against a list of names then fails — which reads
# exactly like a hallucination and is not one.
_TITLE_SEPARATORS = ("\u2014", "\u2013", " - ", ",", "(", "|")


def presenter_names(session):
    """The people a session names, with any job title stripped off."""
    raw = (session.get("presenter") or "").strip()
    if not raw:
        return []
    out = []
    for part in raw.replace(" & ", " and ").split(" and "):
        name = part
        for sep in _TITLE_SEPARATORS:
            name = name.split(sep)[0]
        name = name.strip(" .-\u2014\u2013")
        if name and name.lower() not in {"tbd", "n/a", "team", "oracle team",
                                         "oracle", "presenter", "host"}:
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
    r.record(f"_event_num_days(meeting)  # event {r.event_id}", r.num_days,
             note="from the event record's duration field")
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
        r.record(f"_briefing_window(meeting, day_index={day})",
                 f"{datetime.fromtimestamp(start_ms/1000, tz):%Y-%m-%d %H:%M} \u2192 "
                 f"{datetime.fromtimestamp(end_ms/1000, tz):%H:%M} {tz}",
                 note="the hours actually reserved for this day")
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
        window_min = (end_ms - start_ms) // 60000
        lo, hi = _session_count_range(window_min, r.num_days)
        r.record(f"_session_count_range(window_minutes={window_min}, num_days={r.num_days})",
                 f"({lo}, {hi})  \u2190 day {day} has {len(sessions)} sessions")
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
    r.record(f"_fetch_meeting_context(event_id={r.event_id!r})[\"meeting_details\"][\"company_name\"]",
             truth or "(absent)")
    if not truth:
        return None, "no company on the event record"
    got = (r.result.get("company") or "").strip()
    return got.lower() == truth.lower(), f"agenda {got!r} vs record {truth!r}"


@case("accuracy", "the industry matches the event record")
def _industry(r):
    truth = (r.meeting.get("industry") or "").strip()
    r.record(f"_fetch_meeting_context(event_id={r.event_id!r})[\"meeting_details\"][\"industry\"]",
             truth or "(absent)")
    if not truth:
        return None, "no industry on the event record"
    got = (r.result.get("industry") or "").strip()
    return got.lower() == truth.lower(), f"agenda {got!r} vs record {truth!r}"


@case("accuracy", "the attendee count matches the attendee list")
def _attendee_count(r):
    r.record(f"len(_fetch_meeting_context(event_id={r.event_id!r})[\"attendees\"])",
             f"{len(r.attendees)}  \u2192 " + _brief([a.get("name") for a in r.attendees]))
    if not r.attendees:
        return None, "no attendees on the event record"
    return r.result.get("attendee_count") == len(r.attendees), \
        f"agenda {r.result.get('attendee_count')} vs {len(r.attendees)} on record"


@case("accuracy", "every topic tag is copied from the list the model was shown")
def _topics_real(r):
    """The vocabulary is the list the prompt carried, not everything indexed.

    The generator shows the model a capped slice of the tenant's topics, so
    judging against the whole index would pass tags the model could not have
    seen. Off-list tags are then split: a tag that exists nowhere is invented,
    while one that matches a real topic apart from its wording is a copy
    failure — a weaker fault, and worth naming separately so the count is not
    misread.
    """
    r.record("_available_topics(ACTIVITIES_INDEX, limit=150)",
             f"{len(r.topics)} topics \u2192 " + _brief(r.topics),
             note="exactly the list the prompt carried")
    if not r.topics:
        return None, "no topic vocabulary reached the prompt"
    shown = {t.strip().lower() for t in r.topics}
    used = sorted({(s.get("topic") or "").strip() for s in r.sessions if s.get("topic")})
    off = [t for t in used if t.lower() not in shown]
    if not off:
        return True, f"{len(used)} distinct tags, all copied from the {len(shown)} shown"

    wider = {t.strip().lower() for t in r.wider_topics()}
    variants = [t for t in off if any(t.lower() in w or w in t.lower() for w in wider)]
    invented = [t for t in off if t not in variants]
    detail = []
    if invented:
        detail.append(f"invented: {invented[:3]}")
    if variants:
        detail.append(f"reworded from a real topic: {variants[:3]}")
    return False, "; ".join(detail)


@case("accuracy", "every presenter is a real person from the source data")
def _presenters_real(r):
    known = r.known_people()
    r.record(f"get_suggested_presenters(event_id={r.event_id!r}, limit=100)"
             " + attendees + ranking rationale",
             f"{len(known)} known names \u2192 " + _brief(sorted(known)),
             note="every person the source data knows")
    if not known:
        return None, "no presenter pool to check against"
    invented = []
    for s in r.sessions:
        for name in presenter_names(s):
            if name.lower() not in known:
                invented.append(f"{name} ({s.get('title')})")
    return not invented, f"not in source data: {invented[:4]}" if invented else \
        f"{len(known)} known people, none invented"


@case("accuracy", "no presenter was invented for a session nothing verified")
def _unverified_presenters(r):
    """The narrow version of the hallucination check.

    Sessions the ranking did check are safe by construction. The exposure is
    the sessions it could not — no topic, so no lookup — where the name stands
    on the model's word alone. Those names still have to belong to somebody the
    source data knows.
    """
    unverified = r.unverified_sessions()
    if not unverified:
        return None, "every session went through topic ranking"
    known = r.known_people()
    if not known:
        return None, "no source data to check against"
    invented = []
    for entry in unverified:
        for name in presenter_names({"presenter": entry.get("presenter") or ""}):
            if name.lower() not in known:
                invented.append(f"{name} ({entry.get('session')})")
    return not invented, (f"{len(invented)} of {len(unverified)} unverified sessions "
                          f"name someone unknown: {invented[:3]}" if invented else
                          f"{len(unverified)} unverified sessions, all names known")


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
    # The scheduler folds this into result["scheduling"], not the top level.
    avail = ((r.result.get("scheduling") or {}).get("availability_checked")
             or r.result.get("availability") or {})
    r.record('result["scheduling"]["availability_checked"]', avail or "(absent)",
             note="what the scheduler reports it checked")
    unchecked = avail.get("days_without_availability_check")
    if unchecked is None:
        return None, "no availability summary on the result"
    return not unchecked, (f"unchecked days: {unchecked}" if unchecked else
                           f"{avail.get('presenters_checked', 0)} presenters checked, all days covered")


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
            hits = conflicts.get(email, [])
            r.record(
                f"_check_presenter_conflicts([{email!r}], {bounds[0]}, {bounds[1]}, "
                f"exclude_event_id={str(r.event_id)!r})",
                "free" if not hits else "BUSY: " + _brief([h.get("event_name") for h in hits]),
                note=f"{name} \u2014 day {s.get('day')} {s.get('time_slot')} \u2014 {s.get('title')}",
            )
            for hit in hits:
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
            hits = _check_presenter_conflicts(
                [email], bounds[0], bounds[1], exclude_event_id=str(r.event_id)).get(email)
            r.record(
                f"_check_presenter_conflicts([{email!r}], {bounds[0]}, {bounds[1]}, "
                f"exclude_event_id={str(r.event_id)!r})",
                "free" if not hits else "BUSY: " + _brief([h.get("event_name") for h in hits]),
                note=f"backup {backup.get('presenter_name')} \u2014 day {s.get('day')} "
                     f"{s.get('time_slot')}",
            )
            if hits:
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

AGENDA_MARKERS = ("sessions", "session_count", "agenda_markdown", "agenda_structured")


def find_agenda(payload):
    """Dig a generate_agenda result out of whatever it arrived wrapped in.

    An agenda reaches people through several envelopes — the raw tool return,
    the {"generate_agenda": ...} the handler emits, a whole API response, a
    saved SSE frame — and asking anyone to unwrap it by hand before they can
    check it is how a verification step stops being used. Anything carrying an
    agenda's own keys counts, whatever it is nested inside.
    """
    seen = []

    def walk(node):
        if isinstance(node, dict):
            if sum(1 for k in AGENDA_MARKERS if k in node) >= 2:
                seen.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    if not seen:
        return None
    # The outermost match is the real result; anything nested inside it is a
    # fragment of the same agenda.
    return max(seen, key=lambda d: len(d))


def event_id_of(result, fallback=None):
    """The event this agenda was built for, if it says so."""
    for key in ("event_id", "eventId"):
        if result.get(key):
            return str(result[key])
    prov = (result.get("provenance") or {}).get("summary") or {}
    if prov.get("event_id"):
        return str(prov["event_id"])
    return fallback


def load_run(path, event_id=None):
    """Check an agenda that was generated somewhere else, by someone else."""
    payload = json.loads(Path(path).read_text())
    result = find_agenda(payload)
    if result is None:
        raise SystemExit(
            f"{path}: no agenda in this file. Expected a generate_agenda result, "
            f'or anything containing one (a {{"generate_agenda": ...}} wrapper, '
            f"an API response, a saved SSE frame)."
        )
    resolved = event_id_of(result, event_id)
    if not resolved:
        raise SystemExit(
            f"{path}: the agenda does not name its event, so there is nothing to "
            f"check it against. Pass --event <id> as well."
        )
    return build_run(resolved, result, elapsed=0.0)


def build_run(event_id, result, elapsed):
    """Attach the source data an agenda has to be judged against."""
    try:
        context = _fetch_meeting_context(event_id=str(event_id))
        try:
            # Mirror the generator's own call exactly: the cap decides which
            # topics reach the prompt, and judging against a different slice
            # would flag tags the model was never offered.
            from tools.presenter_suggest import _available_topics, ACTIVITIES_INDEX
            context["available_topics"] = _available_topics(ACTIVITIES_INDEX, limit=150)
        except Exception:
            context["available_topics"] = []
    except Exception as exc:
        print(f"  ! could not fetch ground truth: {exc}")
        context = {}
    return Run(event_id, result, context, elapsed)


def do_run(event_id):
    started = time.time()
    result = generate_agenda(event_id=str(event_id), include_provenance=True)
    elapsed = time.time() - started
    return build_run(event_id, result, elapsed)


def judge(run):
    rows = []
    for group, label, fn in CASES:
        run._current = label
        try:
            verdict, detail = fn(run)
        except Exception as exc:
            verdict, detail = False, f"raised {type(exc).__name__}: {exc}"
        rows.append((group, label, verdict, detail))
    run._current = None
    return rows


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

REPORT_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agenda Verification</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap">
<style>
:root{
  --ground:#0B0E14; --panel:#141922; --panel-2:#1B2230; --rule:#232B39;
  --ink:#C6CEDA; --ink-dim:#7C8798; --ink-bright:#EDF1F6;
  --pass:#4ED8A0; --fail:#FF6B7A; --skip:#FFB454; --claim:#5AC8FA;
  --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
  --sans:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);
     font-size:14px;line-height:1.5;-webkit-font-smoothing:antialiased}
header{padding:22px 24px 18px;border-bottom:1px solid var(--rule)}
h1{margin:0 0 8px;font-size:17px;font-weight:600;color:var(--ink-bright);letter-spacing:-.01em}
.meta{font-family:var(--mono);font-size:11.5px;color:var(--ink-dim);
      display:flex;gap:18px;flex-wrap:wrap}
.meta b{color:var(--ink);font-weight:500}
.tally{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}
.pill{font-family:var(--mono);font-size:11px;padding:3px 9px;border-radius:99px;
      border:1px solid currentColor}
.pill.p{color:var(--pass)} .pill.f{color:var(--fail)} .pill.s{color:var(--skip)}
main{padding:20px 24px 60px;max-width:1500px}
.runs{display:flex;gap:2px;margin-bottom:18px;flex-wrap:wrap}
.runs button{appearance:none;background:var(--panel);border:1px solid var(--rule);
  color:var(--ink-dim);font-family:var(--mono);font-size:11.5px;padding:6px 13px;
  cursor:pointer;border-radius:6px}
.runs button:hover{color:var(--ink)}
.runs button[aria-selected="true"]{color:var(--ink-bright);border-color:var(--claim);
  background:var(--panel-2)}
.runs button:focus-visible{outline:2px solid var(--claim);outline-offset:2px}
.summary{background:var(--panel);border:1px solid var(--rule);border-radius:10px;
  padding:13px 16px;margin-bottom:16px;font-family:var(--mono);font-size:11.5px;
  color:var(--ink-dim);display:flex;gap:20px;flex-wrap:wrap}
.summary b{color:var(--ink);font-weight:500}
.grp{font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--ink-dim);margin:22px 0 8px}
.card{border:1px solid var(--rule);border-radius:10px;background:var(--panel);
  margin-bottom:8px;overflow:hidden}
.card.fail{border-color:color-mix(in srgb, var(--fail) 45%, var(--rule))}
.row{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.35fr);gap:0}
@media(max-width:900px){.row{grid-template-columns:minmax(0,1fr)}}
.left{padding:13px 16px}
.right{padding:13px 16px;border-left:1px solid var(--rule);background:var(--panel-2)}
@media(max-width:900px){.right{border-left:0;border-top:1px solid var(--rule)}}
.vtag{font-family:var(--mono);font-size:9.5px;letter-spacing:.09em;font-weight:600;
  padding:2px 7px;border-radius:4px;display:inline-block;margin-bottom:7px}
.vtag.PASS{color:var(--pass);background:color-mix(in srgb, var(--pass) 13%, transparent)}
.vtag.FAIL{color:var(--fail);background:color-mix(in srgb, var(--fail) 13%, transparent)}
.vtag.SKIP{color:var(--skip);background:color-mix(in srgb, var(--skip) 13%, transparent)}
.claimtxt{color:var(--ink-bright);font-size:13px}
.detail{font-family:var(--mono);font-size:11px;color:var(--ink-dim);margin-top:7px;
  word-break:break-word}
.card.fail .detail{color:color-mix(in srgb, var(--fail) 72%, var(--ink))}
.ev{margin-bottom:11px}
.ev:last-child{margin-bottom:0}
.ev .lbl{font-family:var(--mono);font-size:9.5px;letter-spacing:.08em;text-transform:uppercase;
  color:var(--ink-dim);margin-bottom:3px}
.ev pre{margin:0 0 4px;font-family:var(--mono);font-size:11px;color:var(--claim);
  white-space:pre-wrap;word-break:break-word}
.ev .out{font-family:var(--mono);font-size:11px;color:var(--ink);white-space:pre-wrap;
  word-break:break-word}
.ev .out.busy{color:var(--fail)}
.ev .note{font-size:11px;color:var(--ink-dim);margin-top:2px}
.none{font-family:var(--mono);font-size:11px;color:var(--ink-dim);font-style:italic}
.hidden{display:none!important}
.legend{font-size:12px;color:var(--ink-dim);margin:0 0 16px}
</style>
</head>
<body>
<header>
  <h1>Agenda verification — event <span id="ev"></span></h1>
  <div class="meta">
    <span><b id="m-runs"></b> runs</span>
    <span><b id="m-props"></b> properties each</span>
    <span id="m-gen"></span>
  </div>
  <div class="tally" id="tally"></div>
</header>
<main>
  <p class="legend">Left: what the generated agenda claims. Right: the deterministic call
  that settled it, and what that call returned. Nothing on the right went near the model.</p>
  <div class="runs" id="runs"></div>
  <div class="summary" id="summary"></div>
  <div id="checks"></div>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const esc = s => String(s == null ? '' : s)
  .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const mark = v => v === true ? 'PASS' : (v === null ? 'SKIP' : 'FAIL');

document.getElementById('ev').textContent = D.event;
document.getElementById('m-runs').textContent = D.runs.length;
document.getElementById('m-props').textContent = D.runs.length ? D.runs[0].checks.length : 0;
document.getElementById('m-gen').textContent = D.generated;

const flat = D.runs.flatMap(r => r.checks);
const n = v => flat.filter(c => mark(c.verdict) === v).length;
document.getElementById('tally').innerHTML =
    '<span class="pill p">' + n('PASS') + ' passed</span>'
  + '<span class="pill f">' + n('FAIL') + ' failed</span>'
  + '<span class="pill s">' + n('SKIP') + ' skipped</span>';

document.getElementById('runs').innerHTML = D.runs.map((r, i) => {
  const f = r.checks.filter(c => c.verdict === false).length;
  return '<button role="tab" data-i="' + i + '" aria-selected="' + (i === 0) + '">run '
       + (i + 1) + (f ? ' · ' + f + ' failed' : ' · clean') + '</button>';
}).join('');

function render(i){
  const r = D.runs[i];
  document.getElementById('summary').innerHTML =
      '<span><b>' + r.sessions + '</b> sessions</span>'
    + '<span>days <b>[' + r.days.join(', ') + ']</b></span>'
    + '<span><b>' + r.elapsed.toFixed(1) + 's</b></span>'
    + '<span>ebd <b>' + esc(r.ebd) + '</b></span>'
    + '<span>confidence <b>' + esc(r.confidence) + '</b></span>';

  let html = '', group = null;
  r.checks.forEach(c => {
    if (c.group !== group) { group = c.group; html += '<div class="grp">' + esc(group) + '</div>'; }
    const m = mark(c.verdict);
    const ev = (c.evidence || []).length
      ? c.evidence.map(e =>
          '<div class="ev"><div class="lbl">call</div><pre>' + esc(e.call) + '</pre>'
          + '<div class="out' + (/^BUSY/.test(e.output) ? ' busy' : '') + '">'
          + esc(e.output) + '</div>'
          + (e.note ? '<div class="note">' + esc(e.note) + '</div>' : '')
          + '</div>').join('')
      : '<div class="none">no external call — checked against the agenda itself</div>';
    html += '<div class="card ' + (c.verdict === false ? 'fail' : '') + '"><div class="row">'
          + '<div class="left"><span class="vtag ' + m + '">' + m + '</span>'
          + '<div class="claimtxt">' + esc(c.label) + '</div>'
          + '<div class="detail">' + esc(c.detail) + '</div></div>'
          + '<div class="right">' + ev + '</div></div></div>';
  });
  document.getElementById('checks').innerHTML = html;
  document.querySelectorAll('#runs button').forEach(b =>
    b.setAttribute('aria-selected', String(Number(b.dataset.i) === i)));
}
document.getElementById('runs').addEventListener('click', e => {
  const b = e.target.closest('button'); if (b) render(Number(b.dataset.i));
});
render(0);
</script>
</body>
</html>
"""


def build_report(event, runs, all_rows):
    """Fold the runs into the shape the report page renders."""
    payload = {
        "event": str(event),
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "runs": [],
    }
    for run, rows in zip(runs, all_rows):
        conf = run.result.get("confidence")
        payload["runs"].append({
            "elapsed": round(run.elapsed, 1),
            "sessions": len(run.sessions),
            "days": sorted(run.by_day()),
            "ebd": run.result.get("ebd_status") or "-",
            "confidence": (f"{conf.get('score')} ({conf.get('level')})"
                           if isinstance(conf, dict) else str(conf)),
            "checks": [{
                "group": group,
                "label": label,
                "verdict": verdict,
                "detail": detail,
                "evidence": run.evidence_for(label),
            } for group, label, verdict, detail in rows],
        })
    return payload


def write_report(path, payload):
    Path(path).write_text(REPORT_TEMPLATE.replace("__DATA__", json.dumps(payload, indent=1)))


def main() -> int:
    ap = argparse.ArgumentParser(description="Property checks on a generated agenda.")
    ap.add_argument("--event", help="event id to generate an agenda against")
    ap.add_argument("--agenda", metavar="PATH",
                    help="check an agenda that already exists instead of generating "
                         "one: a saved generate_agenda result, or any JSON containing "
                         "one. No model call is made.")
    ap.add_argument("--repeat", type=int, default=1,
                    help="generate N times; agenda generation is stochastic and "
                         "some failures only show up across runs")
    ap.add_argument("--json", metavar="PATH", help="write the full results here")
    ap.add_argument("--html", metavar="PATH",
                    help="write a report page showing each claim beside the call "
                         "that verified it")
    args = ap.parse_args()

    if not args.event and not args.agenda:
        ap.error("give --event to generate an agenda, or --agenda to check an existing one")

    all_rows, runs = [], []
    sources = ([args.agenda] if args.agenda else [None] * args.repeat)
    for i, source in enumerate(sources):
        if source:
            run = load_run(source, args.event)
            print(f"\n=== checking {source} — event {run.event_id} ===")
        else:
            print(f"\n=== run {i + 1}/{len(sources)} — event {args.event} ===")
            run = do_run(args.event)
        rows = judge(run)
        runs.append(run)
        all_rows.append(rows)

        days = sorted(run.by_day())
        took = f" in {run.elapsed:.1f}s" if run.elapsed else ""
        print(f"  {len(run.sessions)} sessions over days {days}{took} "
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
    if len(runs) > 1:
        print(f"across {len(runs)} runs:")
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
                print(f"  {label}\n      {', '.join(bits)} of {len(runs)}")
        if not any(v is False for rows in all_rows for _g, _l, v, _d in rows):
            print("  every property held on every run")

    total_fail = sum(1 for rows in all_rows for _g, _l, v, _d in rows if v is False)
    total_pass = sum(1 for rows in all_rows for _g, _l, v, _d in rows if v is True)
    total_skip = sum(1 for rows in all_rows for _g, _l, v, _d in rows if v is None)
    print(f"\n{total_pass} passed, {total_fail} failed, {total_skip} skipped "
          f"({len(CASES)} properties x {len(runs)} runs)")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump([{"event": r.event_id, "elapsed": r.elapsed,
                        "sessions": len(r.sessions), "days": sorted(r.by_day()),
                        "checks": [{"group": g, "label": l, "verdict": v, "detail": d}
                                   for g, l, v, d in rows]}
                       for r, rows in zip(runs, all_rows)], fh, indent=2)
        print(f"wrote {args.json}")

    if args.html:
        write_report(args.html, build_report(runs[0].event_id, runs, all_rows))
        print(f"wrote {args.html}")

    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(main())
