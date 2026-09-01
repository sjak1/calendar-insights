"""Tests for tools/agenda_scheduler.py — the pure layout engine.

No network, no OpenSearch, no LLM: the module takes everything as arguments,
which is the whole point of it being separate from agenda_generator.
"""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.agenda_scheduler import (  # noqa: E402
    ANCHOR_ANY,
    ANCHOR_CLOSE,
    ANCHOR_LUNCH,
    ANCHOR_OPEN,
    LayoutResult,
    SessionSpec,
    _fit_to_window,
    _ordered,
    format_time_slot,
    free_gaps,
    layout,
    merge_intervals,
)

MIN = 60 * 1000
DAY = datetime(2026, 3, 10, tzinfo=timezone.utc)


def at(hour, minute=0):
    """Epoch ms for a wall-clock time on the fixture day (UTC)."""
    return int((DAY + timedelta(hours=hour, minutes=minute)).timestamp() * 1000)


def person(name, email=None, busy=None):
    return {"presenter_name": name, "email": email or f"{name.lower()}@x.com",
            "emails": [(email or f"{name.lower()}@x.com")]}


class TestIntervalHelpers(unittest.TestCase):
    def test_merge_collapses_overlapping_and_adjacent(self):
        self.assertEqual(
            merge_intervals([(10, 20), (15, 25), (25, 30), (40, 50)]),
            [(10, 30), (40, 50)],
        )

    def test_merge_drops_zero_and_negative_length_spans(self):
        self.assertEqual(merge_intervals([(10, 10), (20, 15), (30, 40)]), [(30, 40)])

    def test_free_gaps_returns_uncovered_spans(self):
        self.assertEqual(free_gaps(0, 100, [(20, 40)]), [(0, 20), (40, 100)])

    def test_free_gaps_honours_minimum_duration(self):
        self.assertEqual(free_gaps(0, 100, [(20, 40)], min_duration_ms=30), [(40, 100)])

    def test_free_gaps_ignores_busy_outside_window(self):
        self.assertEqual(free_gaps(50, 100, [(0, 10), (200, 300)]), [(50, 100)])

    def test_free_gaps_fully_booked_window_is_empty(self):
        self.assertEqual(free_gaps(0, 100, [(0, 100)]), [])


class TestFormatting(unittest.TestCase):
    def test_time_slot_shape_matches_the_push_parser(self):
        self.assertEqual(format_time_slot(at(10), at(10, 45), timezone.utc),
                         "10:00 AM - 10:45 AM")

    def test_leading_zero_is_stripped(self):
        self.assertEqual(format_time_slot(at(9), at(9, 30), timezone.utc),
                         "9:00 AM - 9:30 AM")

    def test_afternoon_renders_as_pm(self):
        self.assertEqual(format_time_slot(at(13), at(14), timezone.utc),
                         "1:00 PM - 2:00 PM")


class TestSessionSpecNormalisation(unittest.TestCase):
    def test_missing_bounds_default_to_target(self):
        s = SessionSpec(title="t", duration_target=45)
        self.assertEqual((s.duration_min, s.duration_max), (45, 45))

    def test_min_above_target_is_clamped_down(self):
        s = SessionSpec(title="t", duration_target=30, duration_min=45)
        self.assertEqual(s.duration_min, 30)

    def test_max_below_target_is_clamped_up(self):
        s = SessionSpec(title="t", duration_target=30, duration_max=10)
        self.assertEqual(s.duration_max, 30)

    def test_unknown_anchor_falls_back_to_any(self):
        self.assertEqual(SessionSpec(title="t", duration_target=30, anchor="brunch").anchor,
                         ANCHOR_ANY)


class TestOrdering(unittest.TestCase):
    def test_opens_first_closes_last_middle_order_preserved(self):
        a = SessionSpec(title="close", duration_target=15, anchor=ANCHOR_CLOSE)
        b = SessionSpec(title="deep dive", duration_target=60)
        c = SessionSpec(title="welcome", duration_target=15, anchor=ANCHOR_OPEN)
        d = SessionSpec(title="demo", duration_target=45)
        self.assertEqual([s.title for s in _ordered([a, b, c, d])],
                         ["welcome", "deep dive", "demo", "close"])


class TestFitToWindow(unittest.TestCase):
    def _day(self):
        return [
            SessionSpec(title="welcome", duration_target=15, movable=False, anchor=ANCHOR_OPEN),
            SessionSpec(title="strategy", duration_target=60, duration_min=45),
            SessionSpec(title="demo", duration_target=60, duration_min=45),
            SessionSpec(title="close", duration_target=15, movable=False, anchor=ANCHOR_CLOSE),
        ]

    def test_everything_fits_untouched_when_there_is_room(self):
        kept, durations, dropped, leftover = _fit_to_window(self._day(), 480 * MIN)
        self.assertEqual(len(kept), 4)
        self.assertEqual(dropped, [])
        self.assertEqual([d // MIN for d in durations], [15, 60, 60, 15])
        self.assertEqual(leftover, (480 - 150) * MIN)

    def test_longest_sessions_are_compressed_first(self):
        # 150 min of content into 120 min: the two 60s give 15 each, the
        # 15-minute welcome and close are left alone.
        kept, durations, dropped, leftover = _fit_to_window(self._day(), 120 * MIN)
        self.assertEqual(dropped, [])
        self.assertEqual([d // MIN for d in durations], [15, 45, 45, 15])
        self.assertEqual(leftover, 0)

    def test_drops_from_the_back_of_the_movable_middle(self):
        kept, durations, dropped, leftover = _fit_to_window(self._day(), 90 * MIN)
        self.assertEqual([s.title for s in dropped], ["demo"])
        self.assertEqual([s.title for s in kept], ["welcome", "strategy", "close"])

    def test_lunch_and_pinned_slots_survive_a_drop(self):
        specs = [
            SessionSpec(title="welcome", duration_target=15, movable=False, anchor=ANCHOR_OPEN),
            SessionSpec(title="lunch", duration_target=60, movable=False, anchor=ANCHOR_LUNCH),
            SessionSpec(title="filler", duration_target=60),
            SessionSpec(title="close", duration_target=15, movable=False, anchor=ANCHOR_CLOSE),
        ]
        kept, _, dropped, _ = _fit_to_window(specs, 90 * MIN)
        self.assertEqual([s.title for s in dropped], ["filler"])
        self.assertIn("lunch", [s.title for s in kept])


class TestLayoutBasics(unittest.TestCase):
    def test_sessions_are_chronological_non_overlapping_and_inside_the_window(self):
        specs = [SessionSpec(title=f"s{i}", duration_target=60) for i in range(3)]
        r = layout(specs, at(9), at(17), timezone.utc)
        self.assertEqual(len(r.placed), 3)
        self.assertEqual(r.unplaced, [])
        prev_end = at(9)
        for p in r.placed:
            self.assertGreaterEqual(p.start_ms, prev_end)
            self.assertLess(p.start_ms, p.end_ms)
            self.assertLessEqual(p.end_ms, at(17))
            prev_end = p.end_ms

    def test_slack_becomes_a_buffer_between_sessions_not_longer_sessions(self):
        specs = [SessionSpec(title=f"s{i}", duration_target=60) for i in range(3)]
        r = layout(specs, at(9), at(17), timezone.utc)
        self.assertEqual([p.time_slot for p in r.placed],
                         ["9:00 AM - 10:00 AM", "10:15 AM - 11:15 AM", "11:30 AM - 12:30 PM"])

    def test_empty_input_returns_empty_result(self):
        r = layout([], at(9), at(17), timezone.utc)
        self.assertEqual(r.placed, [])
        self.assertEqual(r.unplaced, [])

    def test_inverted_window_places_nothing_and_reports_everything(self):
        specs = [SessionSpec(title="s", duration_target=30)]
        r = layout(specs, at(17), at(9), timezone.utc)
        self.assertEqual(r.placed, [])
        self.assertEqual(len(r.unplaced), 1)

    def test_oversubscribed_day_reports_what_it_dropped(self):
        specs = [SessionSpec(title=f"s{i}", duration_target=60) for i in range(3)]
        r = layout(specs, at(9), at(10), timezone.utc)
        self.assertEqual(len(r.placed), 1)
        self.assertEqual(sorted(s.title for s in r.unplaced), ["s1", "s2"])
        for p in r.placed:
            self.assertLessEqual(p.end_ms, at(10))

    def test_utilization_reports_programmed_fraction(self):
        specs = [SessionSpec(title="s", duration_target=60)]
        r = layout(specs, at(9), at(10), timezone.utc)
        self.assertAlmostEqual(r.utilization, 1.0, places=3)


class TestLayoutAvailabilityLadder(unittest.TestCase):
    """The ordering the briefing team asked for: reshape the day before
    downgrading who presents."""

    def test_rung1_slips_the_session_to_keep_the_top_presenter(self):
        top = person("Ada")
        specs = [SessionSpec(title="strategy", duration_target=60, candidates=[top])]
        busy = {"ada@x.com": [(at(9), at(9, 30))]}
        r = layout(specs, at(9), at(17), timezone.utc, busy)
        p = r.placed[0]
        self.assertEqual(p.presenter["presenter_name"], "Ada")
        self.assertEqual(p.time_slot, "9:30 AM - 10:30 AM")
        self.assertIn("moved 30 min later", p.scheduling_note)
        self.assertFalse(p.has_conflict)

    def test_rung1_refuses_to_slip_beyond_the_cap(self):
        # Busy for 90 minutes — past _MAX_SLIP_MINUTES, so a lone session
        # cannot slip and falls through to the presenter fallback.
        top, alt = person("Ada"), person("Grace")
        specs = [SessionSpec(title="strategy", duration_target=60, candidates=[top, alt])]
        busy = {"ada@x.com": [(at(9), at(10, 30))]}
        r = layout(specs, at(9), at(17), timezone.utc, busy)
        p = r.placed[0]
        self.assertEqual(p.presenter["presenter_name"], "Grace")
        self.assertEqual(p.time_slot, "9:00 AM - 10:00 AM")

    def test_rung2_swaps_a_later_session_forward_to_keep_the_expert(self):
        ada, bob = person("Ada"), person("Bob")
        first = SessionSpec(title="strategy", duration_target=60, candidates=[ada])
        second = SessionSpec(title="demo", duration_target=60, candidates=[bob])
        busy = {"ada@x.com": [(at(9), at(10, 10))]}
        r = layout([first, second], at(9), at(17), timezone.utc, busy)
        titles = [p.spec.title for p in r.placed]
        self.assertEqual(titles, ["demo", "strategy"])
        strategy = r.placed[1]
        self.assertEqual(strategy.presenter["presenter_name"], "Ada")
        self.assertIn("moved later in the day", strategy.scheduling_note)
        self.assertFalse(strategy.has_conflict)

    def test_rung3_falls_back_to_the_next_ranked_free_presenter(self):
        top, alt = person("Ada"), person("Grace")
        specs = [SessionSpec(title="strategy", duration_target=60, candidates=[top, alt])]
        busy = {"ada@x.com": [(at(0), at(23, 59))]}
        r = layout(specs, at(9), at(17), timezone.utc, busy)
        p = r.placed[0]
        self.assertEqual(p.presenter["presenter_name"], "Grace")
        self.assertIn("Ada is booked", p.scheduling_note)
        self.assertFalse(p.has_conflict)

    def test_unavoidable_conflict_is_reported_not_hidden(self):
        top = person("Ada")
        specs = [SessionSpec(title="strategy", duration_target=60, candidates=[top])]
        busy = {"ada@x.com": [(at(0), at(23, 59))]}
        r = layout(specs, at(9), at(17), timezone.utc, busy)
        p = r.placed[0]
        self.assertEqual(p.presenter["presenter_name"], "Ada")
        self.assertTrue(p.has_conflict)
        self.assertIn("double-booked", p.scheduling_note)

    def test_alternates_listed_are_actually_free_for_that_slot(self):
        top, free_alt, busy_alt = person("Ada"), person("Grace"), person("Alan")
        specs = [SessionSpec(title="strategy", duration_target=60,
                             candidates=[top, free_alt, busy_alt])]
        busy = {"alan@x.com": [(at(9), at(17))]}
        r = layout(specs, at(9), at(17), timezone.utc, busy)
        names = [a["presenter_name"] for a in r.placed[0].alternates]
        self.assertEqual(names, ["Grace"])

    def test_all_of_a_persons_addresses_are_checked_for_clashes(self):
        # Dedupe keys on BriefingIQ uniqueId, so `email` is only one of two
        # addresses a presenter holds; a booking filed under the other must
        # still count as busy.
        ada = {"presenter_name": "Ada", "email": "ada@allianceit.com",
               "emails": ["ada@allianceit.com", "ada@briefingiq.com"]}
        specs = [SessionSpec(title="strategy", duration_target=60, candidates=[ada])]
        busy = {"ada@briefingiq.com": [(at(9), at(9, 30))]}
        r = layout(specs, at(9), at(17), timezone.utc, busy)
        self.assertIn("moved 30 min later", r.placed[0].scheduling_note)

    def test_busy_map_keys_are_matched_case_insensitively(self):
        ada = person("Ada", email="Ada@X.com")
        specs = [SessionSpec(title="strategy", duration_target=60, candidates=[ada])]
        busy = {"ADA@X.COM": [(at(9), at(9, 30))]}
        r = layout(specs, at(9), at(17), timezone.utc, busy)
        self.assertEqual(r.placed[0].time_slot, "9:30 AM - 10:30 AM")

    def test_no_candidates_means_no_presenter_and_no_note(self):
        specs = [SessionSpec(title="lunch", duration_target=60, movable=False,
                             anchor=ANCHOR_LUNCH)]
        r = layout(specs, at(12), at(17), timezone.utc, {})
        self.assertIsNone(r.placed[0].presenter)
        self.assertEqual(r.placed[0].scheduling_note, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
