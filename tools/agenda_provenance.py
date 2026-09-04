"""
Provenance for a generated agenda — the receipts behind every presenter pick.

Why this module exists:
  The agenda asserts things it has good reason to believe: "Janice Young —
  Identity Cloud Service: 2 sessions on it, both accepted." The reader has no
  way to check that. The counts are computed over real activity rows and then
  collapsed into a sentence, and the rows are dropped. So a correct pick and a
  hallucinated one read identically.

  This rebuilds the trail: for each session, the topic that was searched, every
  candidate the ranking returned, the individual activity records behind each
  candidate's numbers, who was chosen, and — for the ones who were not — why.

  It also records what availability was actually checked, which is the part
  nobody thinks to ask about. The scheduler now looks up each briefing day
  separately, so days two onward carry real busy spans instead of an empty map
  — but a day's lookup can still fail on its own. When that happens the day is
  absent from `checked_days`, and this trail says so plainly:
  `availability.covers_session` is False and `busy_spans_consulted` is 0,
  rather than letting an unchecked day read as verified.

  Pure by design — no I/O, no network. Everything arrives as arguments, which
  is what makes it testable and what keeps it off the request path.
"""

from typing import Any, Dict, List, Optional

# Candidate fields worth keeping. The ranked pool carries a lot of working
# state; the trail wants the inputs that moved the sort plus the identifiers
# needed to look a person up, and nothing else.
_CANDIDATE_FIELDS = (
    "presenter_name",
    "presenter_id",
    "email",
    "title",
    "match_tier",
    "matched_topic",
    "tier_session_count",
    "session_count",
    "event_count",
    "recency_weighted_sessions",
    "available",
    "reason",
)


def _emails_of(candidate: Dict[str, Any]) -> List[str]:
    """Every address this person is known under, lowercased."""
    emails = {e.lower() for e in (candidate.get("all_emails") or []) if e}
    if candidate.get("email"):
        emails.add(candidate["email"].lower())
    return sorted(emails)


def _name_in(name: str, presenter_field: str) -> bool:
    """Word-boundary name test, matching how the assignment pass compares.

    A bare substring check makes "Dan" match "Danielle", which would credit the
    wrong person with the pick in the trail.
    """
    if not name or not presenter_field:
        return False
    import re

    return re.search(rf"\b{re.escape(name)}\b", presenter_field, re.IGNORECASE) is not None


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


def _covered_days(availability: Optional[Dict[str, Any]]) -> set:
    """The day numbers an availability lookup actually ran for.

    The single source of truth for that question — the summary the model sees
    and the per-session trail must never disagree about which days were checked.

    `checked_days` is authoritative when the scheduler supplies it, because it
    records the days whose lookup *returned*. One day's query can fail while its
    neighbours succeed, and a day that failed must not inherit their coverage
    and read as verified. Payloads without that key predate it and carry only
    the overall window, so fall back to overlapping each day against it.
    """
    availability = availability or {}
    checked = availability.get("checked_days")
    if checked is not None:
        return {int(d) for d in checked}

    win_start = availability.get("window_start_ms") or 0
    win_end = availability.get("window_end_ms") or 0
    out = set()
    for day, win in (availability.get("day_windows") or {}).items():
        d_start, d_end = (win or {}).get("start_ms") or 0, (win or {}).get("end_ms") or 0
        if win_start and win_end and d_start and d_end and _overlaps(
            d_start, d_end, win_start, win_end
        ):
            out.add(int(day))
    return out


def unchecked_days(availability: Optional[Dict[str, Any]]) -> List[int]:
    """Scheduled days that no availability lookup covered, ascending.

    A day in this list was staffed against an empty busy map: every presenter
    read as free there because nothing was looked up for those hours. Callers
    should say so rather than letting the agenda imply a check that never ran.
    """
    availability = availability or {}
    covered = _covered_days(availability)
    return sorted(
        int(day)
        for day in (availability.get("day_windows") or {})
        if int(day) not in covered
    )


def _rejection_reason(
    candidate: Dict[str, Any],
    busy_spans: List[List[int]],
    window_covered: bool,
) -> str:
    """Why this candidate did not get the slot.

    Deliberately narrow: it reports the mechanical reasons this module can see
    from its inputs. Where none applies the honest answer is that someone else
    simply ranked higher, not a guess at the ranker's intent.
    """
    if busy_spans:
        return "already booked during this session"
    if candidate.get("available") is False:
        return "unavailable in the checked window"
    if not window_covered:
        return "outranked (no availability data for this day)"
    return "outranked on topic match or depth"


def build_provenance(
    sessions: List[Any],
    by_topic: Optional[Dict[str, List[Dict[str, Any]]]],
    availability: Optional[Dict[str, Any]] = None,
    max_candidates: int = 5,
) -> Dict[str, Any]:
    """Assemble the provenance block for a scheduled agenda.

    `sessions` are the scheduled agenda sessions (post-layout, so they carry
    their final presenter and time_slot). `by_topic` is the ranked candidate
    pool per topic that the scheduler worked from. `availability` is the
    scheduler's report of the window it checked and the busy spans it found.

    Returns a dict safe to serialise and render. Never raises on partial input:
    an agenda that reached the reader with gaps in its trail is still better
    than one whose trail-builder took the whole response down.
    """
    availability = availability or {}
    by_topic = by_topic or {}

    win_start = availability.get("window_start_ms") or 0
    win_end = availability.get("window_end_ms") or 0
    busy_by_email: Dict[str, List[List[int]]] = availability.get("busy_spans_by_email") or {}
    day_windows: Dict[Any, Dict[str, Any]] = availability.get("day_windows") or {}
    covered_days = _covered_days(availability)

    entries: List[Dict[str, Any]] = []
    days_without_check: List[int] = []

    for sess in sessions:
        day = getattr(sess, "day", None)
        day = day if isinstance(day, int) and day >= 1 else 1
        # day_windows may be keyed by int or by str depending on how it made
        # the trip through serialisation; accept either rather than silently
        # reporting every day as unchecked.
        dw = day_windows.get(day) or day_windows.get(str(day)) or {}
        d_start, d_end = dw.get("start_ms") or 0, dw.get("end_ms") or 0

        covered = day in covered_days
        if not covered and day not in days_without_check:
            days_without_check.append(day)

        topic = (getattr(sess, "topic", None) or "").strip()
        pool = by_topic.get(topic) or []
        chosen_field = (getattr(sess, "presenter", None) or "").strip()

        candidates: List[Dict[str, Any]] = []
        for cand in pool[:max_candidates]:
            name = cand.get("presenter_name") or ""
            spans = [
                span
                for email in _emails_of(cand)
                for span in busy_by_email.get(email, [])
                if d_start and d_end and _overlaps(d_start, d_end, span[0], span[1])
            ]
            selected = _name_in(name, chosen_field)
            row = {k: cand.get(k) for k in _CANDIDATE_FIELDS if cand.get(k) is not None}
            row["emails"] = _emails_of(cand)
            row["source_activities"] = cand.get("source_activities") or []
            row["selected"] = selected
            row["busy_spans_in_this_day"] = spans
            if selected and spans:
                # The scheduler places a busy presenter when no free candidate
                # exists — its documented last resort. The finished agenda shows
                # only the name, so without this the reader cannot tell a clean
                # pick from a knowingly double-booked one.
                row["placed_with_known_conflict"] = True
            if not selected:
                row["rejected_because"] = _rejection_reason(cand, spans, covered)
            candidates.append(row)

        entries.append({
            "session": getattr(sess, "title", "") or "",
            "day": day,
            "time_slot": getattr(sess, "time_slot", "") or "",
            "presenter": chosen_field,
            "topic_used_for_lookup": topic or None,
            "presenter_source": _presenter_source(sess, candidates, topic),
            "candidates": candidates,
            "availability": {
                "day_window": dw.get("label") or "",
                "checked_window_start_ms": win_start or None,
                "checked_window_end_ms": win_end or None,
                "covers_session": covered,
                "busy_spans_consulted": sum(len(c["busy_spans_in_this_day"]) for c in candidates),
            },
        })

    return {
        "sessions": entries,
        "summary": {
            "sessions_total": len(entries),
            "sessions_with_candidate_pool": sum(1 for e in entries if e["candidates"]),
            "days_scheduled_without_availability_check": sorted(days_without_check),
            "presenters_checked": len(availability.get("checked_emails") or []),
        },
        "caveats": _caveats(days_without_check),
    }


def _presenter_source(sess: Any, candidates: List[Dict[str, Any]], topic: str) -> str:
    """Where the name on this session came from.

    Three origins produce identical-looking output in the finished agenda, and
    they carry very different amounts of evidence: the ranking picked from
    history, the model picked and the ranking agreed, or the model picked and
    nothing corroborated it.
    """
    if not (getattr(sess, "presenter", None) or "").strip():
        return "unassigned"
    if getattr(sess, "presenter_before_topic_match", None):
        return "reassigned by topic ranking"
    if any(c["selected"] for c in candidates):
        return "model choice, corroborated by topic ranking"
    if not topic:
        return "model choice, no topic to check against"
    return "model choice, not found in the candidate pool"


def _caveats(days_without_check: List[int]) -> List[str]:
    """Standing limits of this trail, stated rather than left to be discovered."""
    out = [
        "Source activities are the most recent rows behind each candidate's "
        "counts, capped for size — the counts themselves cover every matching "
        "record, so a candidate may have more history than is listed here.",
        "The busy map is built from briefing bookings in the activities index. "
        "Calendar blocks (leave, travel, manual holds) are checked separately "
        "during ranking and are not reflected in busy_spans_in_this_day.",
    ]
    if days_without_check:
        days = ", ".join(str(d) for d in sorted(days_without_check))
        out.append(
            f"No availability was checked for day(s) {days}: the scheduler's "
            "window does not cover them, so every presenter was treated as free. "
            "Presenter picks on those days rest on topic match alone."
        )
    return out
