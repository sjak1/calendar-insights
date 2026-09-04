"""Tests for tools/agenda_provenance.py — the evidence trail behind presenter picks.

Pure module, so everything here is plain data: no network, no OpenSearch, no LLM.
"""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.agenda_provenance import build_provenance  # noqa: E402

DAY1 = datetime(2026, 9, 3, tzinfo=timezone.utc)


def at(day_offset, hour, minute=0):
    """Epoch ms for a wall-clock time N days after the fixture day (UTC)."""
    return int(
        (DAY1 + timedelta(days=day_offset, hours=hour, minutes=minute)).timestamp() * 1000
    )


class Session:
    """Stand-in for AgendaSession — the trail only reads attributes."""

    def __init__(self, title, topic="", presenter="", day=1, time_slot="",
                 presenter_before_topic_match=None):
        self.title = title
        self.topic = topic
        self.presenter = presenter
        self.day = day
        self.time_slot = time_slot
        self.presenter_before_topic_match = presenter_before_topic_match


def candidate(name, email=None, tier="exact match", sources=None, available=None):
    email = email or f"{name.split()[0].lower()}@x.com"
    return {
        "presenter_name": name,
        "email": email,
        "all_emails": [email],
        "title": "Chief Architect",
        "match_tier": tier,
        "matched_topic": "Identity Cloud Service",
        "tier_session_count": 2,
        "session_count": 5,
        "event_count": 3,
        "available": available,
        "reason": f"{tier}: Identity Cloud Service | 2 session(s) on it",
        "source_activities": sources if sources is not None else [
            {"event_id": "EVT-1", "booking_id": "CBR-20260330-3625-031",
             "topic": "Identity Cloud Service", "status": "accepted",
             "date": "2026-03-30", "match_tier": "exact match"},
        ],
    }


def availability(win_start, win_end, days, busy=None):
    return {
        "window_start_ms": win_start,
        "window_end_ms": win_end,
        "checked_emails": ["janice@x.com", "philip@x.com"],
        "busy_spans_by_email": busy or {},
        "day_windows": days,
    }


DAY_WINDOWS_4 = {
    d: {"start_ms": at(d - 1, 7), "end_ms": at(d - 1, 14), "label": "7:00 AM - 2:00 PM"}
    for d in (1, 2, 3, 4)
}


class SourceActivityTests(unittest.TestCase):
    def test_source_rows_survive_into_the_trail(self):
        sessions = [Session("Identity", topic="Identity Cloud Service",
                            presenter="Janice Young — Chief Customer Officer", day=1)]
        prov = build_provenance(
            sessions,
            {"Identity Cloud Service": [candidate("Janice Young")]},
            availability(at(0, 0), at(1, 0), DAY_WINDOWS_4),
        )
        rows = prov["sessions"][0]["candidates"][0]["source_activities"]
        self.assertEqual(rows[0]["booking_id"], "CBR-20260330-3625-031")
        self.assertEqual(rows[0]["status"], "accepted")

    def test_chosen_presenter_is_flagged_selected(self):
        sessions = [Session("Identity", topic="Identity Cloud Service",
                            presenter="Janice Young — Chief Customer Officer")]
        prov = build_provenance(
            sessions,
            {"Identity Cloud Service": [candidate("Janice Young"), candidate("Philip Palmer")]},
            availability(at(0, 0), at(1, 0), DAY_WINDOWS_4),
        )
        cands = prov["sessions"][0]["candidates"]
        self.assertTrue(cands[0]["selected"])
        self.assertFalse(cands[1]["selected"])
        self.assertIn("rejected_because", cands[1])
        self.assertNotIn("rejected_because", cands[0])

    def test_name_match_respects_word_boundaries(self):
        # "Dan" must not be credited with Danielle's session.
        sessions = [Session("Identity", topic="Identity Cloud Service",
                            presenter="Danielle Fox — Chief Architect")]
        prov = build_provenance(
            sessions,
            {"Identity Cloud Service": [candidate("Dan Fox")]},
            availability(at(0, 0), at(1, 0), DAY_WINDOWS_4),
        )
        self.assertFalse(prov["sessions"][0]["candidates"][0]["selected"])


class AvailabilityCoverageTests(unittest.TestCase):
    """The trail's whole reason for existing: saying what was NOT checked."""

    def test_day_one_is_covered_by_a_single_day_window(self):
        sessions = [Session("Kickoff", topic="Cloud Strategy", presenter="Janice Young", day=1)]
        prov = build_provenance(
            sessions,
            {"Cloud Strategy": [candidate("Janice Young")]},
            availability(at(0, 0), at(1, 0), DAY_WINDOWS_4),
        )
        self.assertTrue(prov["sessions"][0]["availability"]["covers_session"])
        self.assertEqual(prov["summary"]["days_scheduled_without_availability_check"], [])

    def test_later_days_are_reported_as_unchecked(self):
        sessions = [
            Session("A", topic="Cloud Strategy", presenter="Janice Young", day=1),
            Session("B", topic="Cloud Strategy", presenter="Janice Young", day=2),
            Session("C", topic="Cloud Strategy", presenter="Janice Young", day=4),
        ]
        prov = build_provenance(
            sessions,
            {"Cloud Strategy": [candidate("Janice Young")]},
            availability(at(0, 0), at(1, 0), DAY_WINDOWS_4),
        )
        self.assertEqual(
            prov["summary"]["days_scheduled_without_availability_check"], [2, 4]
        )
        self.assertFalse(prov["sessions"][1]["availability"]["covers_session"])
        self.assertTrue(
            any("day(s) 2, 4" in c for c in prov["caveats"]),
            prov["caveats"],
        )

    def test_string_keyed_day_windows_are_accepted(self):
        # day_windows may arrive with string keys after a JSON round trip;
        # treating those as missing would report every day as unchecked.
        sessions = [Session("A", topic="Cloud Strategy", presenter="Janice Young", day=1)]
        windows = {str(k): v for k, v in DAY_WINDOWS_4.items()}
        prov = build_provenance(
            sessions,
            {"Cloud Strategy": [candidate("Janice Young")]},
            availability(at(0, 0), at(1, 0), windows),
        )
        self.assertTrue(prov["sessions"][0]["availability"]["covers_session"])

    def test_busy_span_in_the_day_is_recorded_and_explains_rejection(self):
        sessions = [Session("A", topic="Cloud Strategy",
                            presenter="Philip Palmer — CTO", day=1)]
        busy = {"janice@x.com": [[at(0, 9), at(0, 10)]]}
        prov = build_provenance(
            sessions,
            {"Cloud Strategy": [candidate("Janice Young"), candidate("Philip Palmer")]},
            availability(at(0, 0), at(1, 0), DAY_WINDOWS_4, busy=busy),
        )
        janice = prov["sessions"][0]["candidates"][0]
        self.assertEqual(janice["busy_spans_in_this_day"], [[at(0, 9), at(0, 10)]])
        self.assertEqual(janice["rejected_because"], "already booked during this session")

    def test_busy_span_on_another_day_is_not_attributed_to_this_one(self):
        sessions = [Session("A", topic="Cloud Strategy", presenter="Philip Palmer", day=2)]
        busy = {"janice@x.com": [[at(0, 9), at(0, 10)]]}  # a day-1 booking
        prov = build_provenance(
            sessions,
            {"Cloud Strategy": [candidate("Janice Young"), candidate("Philip Palmer")]},
            availability(at(0, 0), at(1, 0), DAY_WINDOWS_4, busy=busy),
        )
        janice = prov["sessions"][0]["candidates"][0]
        self.assertEqual(janice["busy_spans_in_this_day"], [])
        self.assertEqual(
            janice["rejected_because"], "outranked (no availability data for this day)"
        )


    def test_a_free_candidate_beats_a_busy_one_and_the_trail_says_why(self):
        sessions = [Session("A", topic="Cloud Strategy",
                            presenter="Philip Palmer — CTO", day=1)]
        busy = {"janice@x.com": [[at(0, 9), at(0, 10)]]}
        prov = build_provenance(
            sessions,
            {"Cloud Strategy": [candidate("Janice Young"), candidate("Philip Palmer")]},
            availability(at(0, 0), at(1, 0), DAY_WINDOWS_4, busy=busy),
        )
        janice, philip = prov["sessions"][0]["candidates"]
        self.assertEqual(janice["rejected_because"], "already booked during this session")
        self.assertTrue(philip["selected"])
        self.assertNotIn("placed_with_known_conflict", philip)

    def test_selection_despite_a_clash_is_flagged_not_hidden(self):
        sessions = [Session("A", topic="Cloud Strategy",
                            presenter="Janice Young — Chief Customer Officer", day=1)]
        busy = {"janice@x.com": [[at(0, 9), at(0, 10)]]}
        prov = build_provenance(
            sessions,
            {"Cloud Strategy": [candidate("Janice Young")]},
            availability(at(0, 0), at(1, 0), DAY_WINDOWS_4, busy=busy),
        )
        janice = prov["sessions"][0]["candidates"][0]
        self.assertTrue(janice["selected"])
        self.assertTrue(janice["placed_with_known_conflict"])


class PresenterSourceTests(unittest.TestCase):
    def test_reassignment_is_labelled(self):
        sessions = [Session("A", topic="Cloud Strategy", presenter="Janice Young",
                            presenter_before_topic_match="TBD")]
        prov = build_provenance(
            sessions, {"Cloud Strategy": [candidate("Janice Young")]},
            availability(at(0, 0), at(1, 0), DAY_WINDOWS_4),
        )
        self.assertEqual(prov["sessions"][0]["presenter_source"],
                         "reassigned by topic ranking")

    def test_model_pick_not_in_pool_is_called_out(self):
        sessions = [Session("A", topic="Cloud Strategy", presenter="Someone Else")]
        prov = build_provenance(
            sessions, {"Cloud Strategy": [candidate("Janice Young")]},
            availability(at(0, 0), at(1, 0), DAY_WINDOWS_4),
        )
        self.assertEqual(prov["sessions"][0]["presenter_source"],
                         "model choice, not found in the candidate pool")

    def test_model_pick_with_no_topic_is_distinguished(self):
        sessions = [Session("Lunch", topic="", presenter="Janice Young")]
        prov = build_provenance(
            sessions, {}, availability(at(0, 0), at(1, 0), DAY_WINDOWS_4)
        )
        self.assertEqual(prov["sessions"][0]["presenter_source"],
                         "model choice, no topic to check against")

    def test_unassigned_session_is_not_claimed_as_a_choice(self):
        sessions = [Session("Lunch", topic="", presenter="")]
        prov = build_provenance(
            sessions, {}, availability(at(0, 0), at(1, 0), DAY_WINDOWS_4)
        )
        self.assertEqual(prov["sessions"][0]["presenter_source"], "unassigned")


class RobustnessTests(unittest.TestCase):
    def test_missing_availability_does_not_raise(self):
        sessions = [Session("A", topic="Cloud Strategy", presenter="Janice Young")]
        prov = build_provenance(sessions, {"Cloud Strategy": [candidate("Janice Young")]})
        self.assertEqual(prov["summary"]["sessions_total"], 1)
        self.assertFalse(prov["sessions"][0]["availability"]["covers_session"])

    def test_no_candidate_pool_still_produces_an_entry(self):
        sessions = [Session("A", topic="Nobody Presents This", presenter="Janice Young")]
        prov = build_provenance(sessions, {}, availability(at(0, 0), at(1, 0), DAY_WINDOWS_4))
        self.assertEqual(prov["sessions"][0]["candidates"], [])
        self.assertEqual(prov["summary"]["sessions_with_candidate_pool"], 0)

    def test_candidate_list_is_capped(self):
        pool = [candidate(f"Person{i} Last") for i in range(10)]
        sessions = [Session("A", topic="Cloud Strategy", presenter="Person0 Last")]
        prov = build_provenance(
            sessions, {"Cloud Strategy": pool},
            availability(at(0, 0), at(1, 0), DAY_WINDOWS_4), max_candidates=3,
        )
        self.assertEqual(len(prov["sessions"][0]["candidates"]), 3)

    def test_caveats_always_state_the_standing_limits(self):
        prov = build_provenance([], {}, availability(at(0, 0), at(1, 0), DAY_WINDOWS_4))
        joined = " ".join(prov["caveats"])
        self.assertIn("capped for size", joined)
        self.assertIn("Calendar blocks", joined)


if __name__ == "__main__":
    unittest.main()
