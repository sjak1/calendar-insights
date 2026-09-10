"""Tests for tools/briefingiq_writer.py — the agenda push.

Every HTTP helper is patched out, so these assert the push's own logic:
which calendar date each session lands on, and whether the result tells the
truth about what was created. No network, no BriefingIQ, no token.
"""

import os
import sys
import unittest
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import briefingiq_writer as bw  # noqa: E402

EVENT = "event-uuid"
DATE = "2026-03-02"  # a Monday


def sess(title, slot, day=None):
    s = {"title": title, "time_slot": slot}
    if day is not None:
        s["day"] = day
    return s


class DateForDayTests(unittest.TestCase):
    """_date_for_day is the whole multi-day fix; test it directly."""

    def test_day_one_is_the_event_date(self):
        self.assertEqual(bw._date_for_day(DATE, 1), DATE)

    def test_missing_day_is_treated_as_day_one(self):
        self.assertEqual(bw._date_for_day(DATE, None), DATE)

    def test_later_days_advance_the_calendar(self):
        self.assertEqual(bw._date_for_day(DATE, 2), "2026-03-03")
        self.assertEqual(bw._date_for_day(DATE, 4), "2026-03-05")

    def test_day_may_arrive_as_a_string(self):
        self.assertEqual(bw._date_for_day(DATE, "3"), "2026-03-04")

    def test_junk_day_falls_back_to_day_one(self):
        for junk in ("", "Day 2", [], {}, 0, -5):
            self.assertEqual(bw._date_for_day(DATE, junk), DATE, junk)

    def test_it_crosses_a_month_boundary(self):
        self.assertEqual(bw._date_for_day("2026-03-30", 4), "2026-04-02")

    def test_explicit_dates_win_over_consecutive_days(self):
        # A briefing that skips the weekend: day 3 is the Monday, not Saturday.
        day_dates = {1: "2026-03-06", 2: "2026-03-09", 3: "2026-03-10"}
        self.assertEqual(bw._date_for_day("2026-03-06", 3, day_dates), "2026-03-10")

    def test_explicit_dates_accept_string_keys(self):
        self.assertEqual(bw._date_for_day(DATE, 2, {"2": "2026-04-01"}), "2026-04-01")

    def test_explicit_dates_fall_through_when_the_day_is_absent(self):
        self.assertEqual(bw._date_for_day(DATE, 2, {1: DATE}), "2026-03-03")

    def test_unparseable_event_date_is_returned_untouched(self):
        self.assertEqual(bw._date_for_day("not-a-date", 2), "not-a-date")


class PushBase(unittest.TestCase):
    """Patches every outbound call so push_agenda_to_app runs offline."""

    def setUp(self):
        self.created_activities = []
        self.presenters = []
        self.fail_titles = set()
        self._seq = 0

        def fake_create_activity(headers, event_id, event_date, start_iso, end_iso,
                                 duration, resource_id=None):
            self._seq += 1
            self.created_activities.append({
                "event_date": event_date, "start_iso": start_iso,
                "end_iso": end_iso, "duration": duration,
            })
            return f"activity-{self._seq}"

        patches = [
            patch.object(bw, "_make_headers", return_value={}),
            patch.object(bw, "_fetch_topics", return_value=[]),
            patch.object(bw, "_create_activity", side_effect=fake_create_activity),
            patch.object(bw, "_fuzzy_match_topic", return_value={"name": "T", "id": "t1"}),
            patch.object(bw, "_create_topic", return_value={"name": "T", "id": "t1"}),
            patch.object(bw, "_set_topic", return_value=True),
            patch.object(bw, "_add_presenter",
                         side_effect=lambda h, a, e: self.presenters.append((a, e))),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def push(self, sessions, **kw):
        return bw.push_agenda_to_app(
            event_id=EVENT, event_date=DATE, sessions=sessions, token="tok", **kw
        )


class MultiDayPushTests(PushBase):

    def test_a_four_day_agenda_lands_on_four_dates(self):
        sessions = [
            sess("Welcome", "09:00 AM - 09:15 AM", day=1),
            sess("Day 2 Opening", "09:00 AM - 09:15 AM", day=2),
            sess("Day 3 Opening", "09:00 AM - 09:15 AM", day=3),
            sess("Closing", "09:00 AM - 09:15 AM", day=4),
        ]
        result = self.push(sessions)

        self.assertEqual(
            result["dates"],
            ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05"],
        )
        starts = [a["start_iso"] for a in self.created_activities]
        self.assertEqual(len(set(starts)), 4, f"sessions stacked on one date: {starts}")

    def test_each_activity_is_filed_under_its_own_day(self):
        # _create_activity also stamps activityDate; it must move with the session.
        self.push([sess("A", "09:00 AM - 10:00 AM", day=1),
                   sess("B", "09:00 AM - 10:00 AM", day=3)])
        self.assertEqual([a["event_date"] for a in self.created_activities],
                         ["2026-03-02", "2026-03-04"])

    def test_the_created_rows_carry_their_date(self):
        result = self.push([sess("A", "09:00 AM - 10:00 AM", day=2)])
        self.assertEqual(result["created"][0]["date"], "2026-03-03")

    def test_a_single_day_agenda_is_unchanged(self):
        sessions = [sess("A", "09:00 AM - 10:00 AM"), sess("B", "10:00 AM - 11:00 AM")]
        result = self.push(sessions)
        self.assertEqual(result["dates"], [DATE])
        self.assertTrue(all(a["start_iso"].startswith(DATE) for a in self.created_activities))

    def test_explicit_day_dates_are_honoured_end_to_end(self):
        result = self.push(
            [sess("A", "09:00 AM - 10:00 AM", day=1), sess("B", "09:00 AM - 10:00 AM", day=2)],
            day_dates={1: "2026-03-06", 2: "2026-03-09"},
        )
        self.assertEqual(result["dates"], ["2026-03-06", "2026-03-09"])


class SuccessFlagTests(PushBase):

    def test_a_clean_push_succeeds(self):
        result = self.push([sess("A", "09:00 AM - 10:00 AM")])
        self.assertTrue(result["success"])
        self.assertEqual(result["failed_count"], 0)
        self.assertNotIn("status", result)

    def test_a_partial_push_does_not_report_success(self):
        with patch.object(bw, "_create_activity",
                          side_effect=[None, "activity-1"]):
            result = self.push([sess("A", "09:00 AM - 10:00 AM"),
                                sess("B", "10:00 AM - 11:00 AM")])
        self.assertFalse(result["success"], "a push that dropped a session claimed success")
        self.assertEqual(result["created_count"], 1)
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(result["status"], "partial")

    def test_a_total_failure_is_reported_as_failed(self):
        with patch.object(bw, "_create_activity", return_value=None):
            result = self.push([sess("A", "09:00 AM - 10:00 AM")])
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["created_count"], 0)

    def test_a_failed_session_records_the_date_it_was_meant_for(self):
        with patch.object(bw, "_create_activity", return_value=None):
            result = self.push([sess("A", "09:00 AM - 10:00 AM", day=3)])
        self.assertEqual(result["failed"][0]["date"], "2026-03-04")

    def test_an_empty_push_is_not_a_failure(self):
        result = self.push([])
        self.assertTrue(result["success"])
        self.assertEqual(result["dates"], [])


class ConflictPreflightTests(PushBase):
    """The pre-flight compares sessions to existing room bookings.

    Before the fix it compared every session against day one, so a booking on
    a later day was invisible and a day-one booking hit every session.
    """

    TZ = "America/Los_Angeles"

    def ms(self, date_str, hour, minute=0):
        try:
            from zoneinfo import ZoneInfo
        except ImportError:  # pragma: no cover - py<3.9 only
            self.skipTest("zoneinfo unavailable")
        dt = datetime(*map(int, date_str.split("-")), hour, minute,
                      tzinfo=ZoneInfo(self.TZ))
        return int(dt.timestamp() * 1000)

    def push_against(self, sessions, bookings):
        with patch.object(bw, "get_resource_schedule", return_value=bookings):
            return bw.push_agenda_to_app(
                event_id=EVENT, event_date=DATE, sessions=sessions, token="tok",
                resource_id="room-1",
                schedule_headers={"x-cloud-requested-timezone": self.TZ},
            )

    def test_a_booking_on_day_two_blocks_the_day_two_session(self):
        booking = {"start_utc_ms": self.ms("2026-03-03", 9),
                   "end_utc_ms": self.ms("2026-03-03", 10),
                   "kind": "BLOCKED", "comments": "Room held"}
        result = self.push_against(
            [sess("Day 1", "09:00 AM - 10:00 AM", day=1),
             sess("Day 2", "09:00 AM - 10:00 AM", day=2)],
            [booking],
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "conflicts")
        self.assertEqual([c["session"] for c in result["conflicts"]], ["Day 2"])
        self.assertEqual(result["conflicts"][0]["session_date"], "2026-03-03")

    def test_a_day_one_booking_does_not_block_later_days(self):
        booking = {"start_utc_ms": self.ms(DATE, 9), "end_utc_ms": self.ms(DATE, 10),
                   "kind": "BLOCKED", "comments": "Room held"}
        result = self.push_against(
            [sess("Day 2", "09:00 AM - 10:00 AM", day=2),
             sess("Day 3", "09:00 AM - 10:00 AM", day=3)],
            [booking],
        )
        self.assertTrue(result["success"], result.get("conflicts"))
        self.assertEqual(result["created_count"], 2)


if __name__ == "__main__":
    unittest.main()
