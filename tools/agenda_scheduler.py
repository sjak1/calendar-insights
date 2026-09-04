"""
Deterministic agenda layout — assigns clock times and presenters to sessions.

Why this module exists:
  The model used to write `time_slot` itself, against the AGENDA_DAY_START/END
  env defaults, with no knowledge of the event's real booked window or of who
  is free when. That produced agendas for the wrong hours (a briefing booked
  08:30-16:30 got a 10:00-17:00 agenda) staffed by people already busy, with
  availability reported afterwards as a warning nobody acted on.

  So the split is: the model decides CONTENT (what sessions, in what order,
  roughly how long), this module decides the CLOCK and, where it has to, WHO.
  Availability is an input to placement here, not a postscript.

  Pure by design — no I/O, no imports from the rest of the app. Everything it
  needs arrives as arguments, which is what makes it testable without network.
"""

from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Anchors constrain WHERE in the day a session may sit.
ANCHOR_OPEN = "open"
ANCHOR_MORNING = "morning"
ANCHOR_LUNCH = "lunch"
ANCHOR_AFTERNOON = "afternoon"
ANCHOR_CLOSE = "close"
ANCHOR_ANY = "any"
ANCHORS = {
    ANCHOR_OPEN, ANCHOR_MORNING, ANCHOR_LUNCH,
    ANCHOR_AFTERNOON, ANCHOR_CLOSE, ANCHOR_ANY,
}

_MIN_MS = 60 * 1000

# How far a session may slip later than its natural start to keep the best
# presenter. Beyond this the day grows holes, which costs more than the swap.
_MAX_SLIP_MINUTES = 45
# How many sessions ahead we look for a swap partner.
_SWAP_LOOKAHEAD = 3
# Breathing room inserted between sessions when the window has slack. A day
# programmed wall-to-wall leaves no room for the conversation that is the
# actual point of a briefing.
_MAX_BUFFER_MINUTES = 15


@dataclass
class SessionSpec:
    """What the model produces: content and shape, but no clock."""

    title: str
    duration_target: int                     # minutes
    duration_min: Optional[int] = None       # defaults to target
    duration_max: Optional[int] = None       # defaults to target
    anchor: str = ANCHOR_ANY
    movable: bool = True
    topic: Optional[str] = None
    # Ranked presenters, best first. Each needs at least {"presenter_name"};
    # "emails" (list) is what availability is keyed on.
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    # Anything the caller wants carried through to the placed result.
    payload: Any = None

    def __post_init__(self):
        if self.duration_min is None:
            self.duration_min = self.duration_target
        if self.duration_max is None:
            self.duration_max = self.duration_target
        # A max below min is a data error, not a constraint — normalise rather
        # than raising, since this sits behind a model that may emit anything.
        self.duration_min = max(1, min(self.duration_min, self.duration_target))
        self.duration_max = max(self.duration_target, self.duration_max)
        if self.anchor not in ANCHORS:
            self.anchor = ANCHOR_ANY


@dataclass
class PlacedSession:
    """What the scheduler produces: the same session, now on the clock."""

    spec: SessionSpec
    start_ms: int
    end_ms: int
    time_slot: str
    presenter: Optional[Dict[str, Any]] = None
    alternates: List[Dict[str, Any]] = field(default_factory=list)
    scheduling_note: str = ""
    # True when we had to place someone who is busy — the honest last resort.
    has_conflict: bool = False


@dataclass
class LayoutResult:
    """Placement outcome, including what would not fit.

    `unplaced` exists because silently dropping sessions is the one failure the
    caller must never make on the reader's behalf: an agenda missing its closing
    session looks complete. Anything trimmed is reported so it can be surfaced.
    """

    placed: List[PlacedSession] = field(default_factory=list)
    unplaced: List[SessionSpec] = field(default_factory=list)
    window_start_ms: int = 0
    window_end_ms: int = 0

    @property
    def programmed_ms(self) -> int:
        return sum(p.end_ms - p.start_ms for p in self.placed)

    @property
    def utilization(self) -> float:
        """Fraction of the booked window actually programmed (0.0-1.0)."""
        span = self.window_end_ms - self.window_start_ms
        return (self.programmed_ms / span) if span > 0 else 0.0


# ---------------------------------------------------------------------------
# Interval helpers
#
# The merge + gap walk mirrors find_vacant_slots() in briefingiq_writer, which
# does the same thing for rooms. Kept here in interval form (no I/O, no tz) so
# both room and presenter scheduling can share one implementation.
# ---------------------------------------------------------------------------

def merge_intervals(intervals: Sequence[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """Collapse overlapping/adjacent (start, end) pairs into disjoint spans."""
    clean = sorted((s, e) for s, e in intervals if e > s)
    merged: List[Tuple[int, int]] = []
    for start, end in clean:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def free_gaps(
    window_start: int,
    window_end: int,
    busy: Sequence[Tuple[int, int]],
    min_duration_ms: int = 0,
) -> List[Tuple[int, int]]:
    """Spans inside the window not covered by `busy`, at least min_duration long."""
    gaps: List[Tuple[int, int]] = []
    cursor = window_start
    for start, end in merge_intervals(busy):
        if end <= window_start or start >= window_end:
            continue
        start = max(start, window_start)
        if start - cursor >= min_duration_ms and start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, min(end, window_end))
    if window_end - cursor >= min_duration_ms and window_end > cursor:
        gaps.append((cursor, window_end))
    return gaps


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


def _candidate_emails(candidate: Dict[str, Any]) -> List[str]:
    """Every address a presenter holds — bookings may be filed under any of them."""
    emails = candidate.get("emails") or candidate.get("all_emails") or []
    if isinstance(emails, str):
        emails = [emails]
    single = candidate.get("email")
    if single and single not in emails:
        emails = list(emails) + [single]
    return [e.lower() for e in emails if e]


def _is_free(
    candidate: Optional[Dict[str, Any]],
    start_ms: int,
    end_ms: int,
    busy_map: Dict[str, List[Tuple[int, int]]],
) -> bool:
    """True when nothing in the busy map clashes with [start, end) for this person.

    Absence of evidence is treated as free — the busy map only knows about
    briefing bookings and calendar blocks we could see. Callers get told which
    rung of the ladder fired, so a silent assumption never reads as a checked fact.
    """
    if not candidate:
        return True
    for email in _candidate_emails(candidate):
        for b_start, b_end in busy_map.get(email, []):
            if _overlaps(start_ms, end_ms, b_start, b_end):
                return False
    return True


def format_time_slot(start_ms: int, end_ms: int, tz: Optional[tzinfo]) -> str:
    """'10:00 AM - 10:45 AM' — the shape push_agenda_to_briefingiq parses."""
    def _fmt(ms: int) -> str:
        dt = datetime.fromtimestamp(ms / 1000, tz=tz) if tz else datetime.utcfromtimestamp(ms / 1000)
        # %-I is platform-specific; strip the zero by hand so this holds on any OS.
        return dt.strftime("%I:%M %p").lstrip("0")

    return f"{_fmt(start_ms)} - {_fmt(end_ms)}"


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------

def _ordered(specs: Sequence[SessionSpec]) -> List[SessionSpec]:
    """Opens to the front, closes to the back; everything else keeps model order.

    Deliberately not a full sort by anchor: the model's sequence carries the
    narrative of the day, and reordering it wholesale to satisfy a coarse
    morning/afternoon hint destroys more than it fixes.
    """
    opens = [s for s in specs if s.anchor == ANCHOR_OPEN]
    closes = [s for s in specs if s.anchor == ANCHOR_CLOSE]
    middle = [s for s in specs if s.anchor not in (ANCHOR_OPEN, ANCHOR_CLOSE)]
    return opens + middle + closes


def _fit_to_window(
    specs: List[SessionSpec], available_ms: int
) -> Tuple[List[SessionSpec], List[int], List[SessionSpec], int]:
    """Choose a duration per session that fits the window.

    Starts at each session's target. If the day is over-subscribed, compresses
    flexible sessions toward their minimum, longest first — a 15-minute welcome
    should not be shaved to 12 while a 90-minute deep-dive keeps its full slot.

    If it still does not fit after full compression, sessions are dropped from
    the back of the movable middle. Opens, closes and pinned slots survive: an
    agenda that loses its closing session is worse than one that loses a
    mid-afternoon deep-dive, and both beat one that overruns the booking.

    Returns (kept, durations_ms, dropped, leftover_ms).
    """
    kept = list(specs)
    dropped: List[SessionSpec] = []

    def _compress(items: List[SessionSpec]) -> Tuple[List[int], int]:
        durations = [s.duration_target * _MIN_MS for s in items]
        total = sum(durations)
        order = sorted(range(len(items)), key=lambda i: -durations[i])
        for i in order:
            if total <= available_ms:
                break
            floor_ms = items[i].duration_min * _MIN_MS
            give = min(durations[i] - floor_ms, total - available_ms)
            if give > 0:
                durations[i] -= give
                total -= give
        return durations, total

    durations, total = _compress(kept)

    # Still over even at every minimum → drop, last movable middle session first.
    while total > available_ms:
        victim = next(
            (
                i
                for i in range(len(kept) - 1, -1, -1)
                if kept[i].movable
                and kept[i].anchor not in (ANCHOR_OPEN, ANCHOR_CLOSE, ANCHOR_LUNCH)
            ),
            None,
        )
        if victim is None:
            break  # only pinned sessions left; placement will truncate honestly
        dropped.append(kept.pop(victim))
        durations, total = _compress(kept)

    return kept, durations, dropped, max(0, available_ms - total)


# ---------------------------------------------------------------------------
# Placement
# ---------------------------------------------------------------------------

def _next_free_start(
    candidate: Dict[str, Any],
    earliest_ms: int,
    duration_ms: int,
    window_end: int,
    busy_map: Dict[str, List[Tuple[int, int]]],
) -> Optional[int]:
    """Earliest start at/after `earliest_ms` where this person is free for the
    whole duration, or None if there is no such start inside the window."""
    busy: List[Tuple[int, int]] = []
    for email in _candidate_emails(candidate):
        busy.extend(busy_map.get(email, []))
    for gap_start, gap_end in free_gaps(earliest_ms, window_end, busy, duration_ms):
        return gap_start
    return None


def _pick_free_candidate(
    candidates: Sequence[Dict[str, Any]],
    start_ms: int,
    end_ms: int,
    busy_map: Dict[str, List[Tuple[int, int]]],
) -> Optional[Dict[str, Any]]:
    """First candidate in rank order who is free for this exact slot."""
    for cand in candidates:
        if _is_free(cand, start_ms, end_ms, busy_map):
            return cand
    return None


def layout(
    specs: Sequence[SessionSpec],
    window_start_ms: int,
    window_end_ms: int,
    tz: Optional[tzinfo] = None,
    busy_map: Optional[Dict[str, List[Tuple[int, int]]]] = None,
) -> LayoutResult:
    """Place sessions on the clock inside the event's real window.

    When the top-ranked presenter for a session is busy, the ladder is:

      1. slip the session later (up to _MAX_SLIP_MINUTES) so they can make it
      2. swap it with a nearby movable session so it lands when they are free
      3. only then fall back to the next-ranked presenter

    Reshaping the day to keep the best person comes before downgrading who
    presents — the ordering the briefing team asked for. Whichever rung fired
    is recorded on the placed session, so the agenda can show its working.
    """
    specs = _ordered([s for s in specs if s is not None])
    result = LayoutResult(window_start_ms=window_start_ms, window_end_ms=window_end_ms)
    if not specs or window_end_ms <= window_start_ms:
        result.unplaced = list(specs)
        return result

    busy_map = {k.lower(): merge_intervals(v) for k, v in (busy_map or {}).items()}

    available = window_end_ms - window_start_ms
    specs, durations, dropped, leftover = _fit_to_window(specs, available)
    result.unplaced.extend(dropped)

    # Spread any slack between sessions rather than stretching them. Whitespace
    # is agenda content, not waste.
    gaps_count = max(1, len(specs) - 1)
    buffer_ms = min(_MAX_BUFFER_MINUTES * _MIN_MS, leftover // gaps_count)

    queue = list(specs)
    dur_by_spec = {id(s): d for s, d in zip(specs, durations)}
    # Why a session ended up later than the model put it. Recorded at swap time
    # because by the time it is finally placed its presenter is free, so there
    # would be nothing left to explain the move.
    pending_notes: Dict[int, str] = {}

    placed: List[PlacedSession] = []
    cursor = window_start_ms
    i = 0

    while i < len(queue):
        spec = queue[i]
        duration = dur_by_spec[id(spec)]
        start = cursor
        end = min(start + duration, window_end_ms)
        if end <= start:
            # Window exhausted. Report the remainder rather than dropping it.
            result.unplaced.extend(queue[i:])
            break

        candidates = list(spec.candidates or [])
        top = candidates[0] if candidates else None
        note = pending_notes.pop(id(spec), "")
        chosen = top
        conflict = False

        if top is not None and not _is_free(top, start, end, busy_map):
            name = top.get("presenter_name") or "the preferred presenter"

            # Rung 1 — slip later, within reason.
            slip_start = _next_free_start(top, start, duration, window_end_ms, busy_map)
            slipped = (
                slip_start is not None
                and (slip_start - start) <= _MAX_SLIP_MINUTES * _MIN_MS
                and slip_start + duration <= window_end_ms
            )
            if slipped:
                delay = (slip_start - start) // _MIN_MS
                start, end = slip_start, slip_start + duration
                # A pending note means this session was ALREADY swapped back to
                # reach this slot. Overwriting it reported a 90-minute reorder
                # as "moved 15 min later" — the note is how the agenda shows its
                # working, so it has to carry the whole move, not the last step.
                note = (
                    f"{note}, and a further {delay} min to clear their calendar"
                    if note
                    else f"moved {delay} min later to keep {name}"
                )
            else:
                # Rung 2 — swap with a nearby movable session whose own top
                # presenter can take this slot, so `spec` lands later where its
                # preferred presenter is actually free.
                swapped = False
                if spec.movable:
                    for j in range(i + 1, min(i + 1 + _SWAP_LOOKAHEAD, len(queue))):
                        other = queue[j]
                        if not other.movable or other.anchor in (ANCHOR_OPEN, ANCHOR_CLOSE):
                            continue
                        other_dur = dur_by_spec[id(other)]
                        other_end = min(start + other_dur, window_end_ms)
                        other_top = (other.candidates or [None])[0]
                        if other_end <= start or not _is_free(other_top, start, other_end, busy_map):
                            continue
                        # Only worth it if `spec` gains something by moving back.
                        later_start = _next_free_start(
                            top, other_end, duration, window_end_ms, busy_map
                        )
                        if later_start is None:
                            continue
                        queue[i], queue[j] = queue[j], queue[i]
                        pending_notes[id(spec)] = (
                            f"moved later in the day so {name} can present it"
                        )
                        swapped = True
                        break
                if swapped:
                    continue  # re-enter the loop with the swapped session at i

                # Rung 3 — keep the slot, take the next available presenter.
                alt = _pick_free_candidate(candidates[1:], start, end, busy_map)
                if alt is not None:
                    chosen = alt
                    fallback = (
                        f"{name} is booked at this time; "
                        f"{alt.get('presenter_name') or 'next-ranked presenter'} takes the session"
                    )
                else:
                    chosen = top
                    conflict = True
                    fallback = f"{name} is double-booked — no free alternate for this slot"
                # Same reasoning as the slip branch: a move already made is part
                # of the explanation, even when it did not end up helping.
                note = f"{note}, but {fallback}" if note else fallback

        alternates = [c for c in candidates if c is not chosen]
        alternates = [
            c for c in alternates if _is_free(c, start, end, busy_map)
        ][:2]

        placed.append(
            PlacedSession(
                spec=spec,
                start_ms=start,
                end_ms=end,
                time_slot=format_time_slot(start, end, tz),
                presenter=chosen,
                alternates=alternates,
                scheduling_note=note,
                has_conflict=conflict,
            )
        )

        cursor = end + buffer_ms
        i += 1

    result.placed = placed
    return result
