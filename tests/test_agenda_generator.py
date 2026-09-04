"""Tests for the deterministic parts of tools/agenda_generator.py.

Everything here runs offline: the LLM call, OpenSearch and Oracle are never
touched. What IS covered is the scheduling logic added on this branch — the
booked-window derivation, the validation that now checks against real hours,
and the phase-three pass that puts an agenda on the clock.
"""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tools.agenda_generator as ag  # noqa: E402
from tools.agenda_generator import (  # noqa: E402
    AgendaSession,
    GeneratedAgenda,
    StrategicNotes,
    _briefing_window,
    _event_location,
    _event_num_days,
    _event_timezone,
    _fallback_window,
    _parse_clock,
    _parse_time_slot,
    _schedule_agenda_sessions,
    _session_count_range,
    _schedule_summary,
    _validate_agenda_sessions,
)

NY = ZoneInfo("America/New_York")


def ms(dt):
    return int(dt.timestamp() * 1000)


def meeting_ny(start=(8, 30), end=(16, 30), day=10, **extra):
    """A briefing booked for real hours on 2026-03-10 in New York."""
    base = datetime(2026, 3, day, tzinfo=NY)
    m = {
        "event_id": "12345",
        "timezone": "America/New_York",
        "start_time_ms": ms(base.replace(hour=start[0], minute=start[1])),
        "end_time_ms": ms(base.replace(hour=end[0], minute=end[1])) if end else None,
    }
    m.update(extra)
    return m


def session(title, slot="", day=1, duration=45, **kw):
    return AgendaSession(
        day=day, time_slot=slot, duration_minutes=duration, title=title,
        format=kw.pop("format", "Presentation"),
        presenter=kw.pop("presenter", "Ada Lovelace — Chief Architect"),
        description="desc", **kw,
    )


def agenda_of(*sessions):
    return GeneratedAgenda(
        company="Acme", industry="Retail", date_time="TBD", location="TBD",
        oracle_presenters=[], total_attendees=10, c_level_count=1,
        decision_maker_count=2, technical_count=3, remote_count=0,
        executive_summary="summary", sessions=list(sessions),
        strategic_notes=StrategicNotes(),
    )


class TestClockParsing(unittest.TestCase):
    def test_parses_am_and_pm(self):
        self.assertEqual(_parse_clock("10:00 AM"), 600)
        self.assertEqual(_parse_clock("5:00 PM"), 1020)

    def test_tolerates_dots_and_spacing(self):
        self.assertEqual(_parse_clock(" 9:30 a.m. "), 570)

    def test_rejects_garbage(self):
        self.assertIsNone(_parse_clock("half past ten"))
        self.assertIsNone(_parse_clock(""))

    def test_time_slot_round_trip(self):
        self.assertEqual(_parse_time_slot("10:00 AM - 10:45 AM"), (600, 645))

    def test_time_slot_needs_two_times(self):
        self.assertIsNone(_parse_time_slot("10:00 AM onwards"))


class TestEventLocation(unittest.TestCase):
    def test_reads_nested_location_data(self):
        hit = {"location": [{"data": [{"locationName": "Oracle EBC",
                                       "addressLine1": "500 Oracle Pkwy",
                                       "city": "Redwood City", "state": "CA"}]}]}
        self.assertEqual(_event_location(hit),
                         "Oracle EBC — 500 Oracle Pkwy — Redwood City, CA")

    def test_falls_back_to_generic_text_fields(self):
        hit = {"location": {"data": {"textField1": "Austin Hub"}}}
        self.assertEqual(_event_location(hit), "Austin Hub")

    def test_missing_location_is_empty_not_an_error(self):
        self.assertEqual(_event_location({}), "")
        self.assertEqual(_event_location({"location": []}), "")
        self.assertEqual(_event_location({"location": "somewhere"}), "")


class TestEventTimezone(unittest.TestCase):
    def test_uses_the_events_own_zone(self):
        self.assertEqual(_event_timezone({"timezone": "America/New_York"}), NY)

    def test_unknown_zone_falls_back_to_utc(self):
        self.assertEqual(_event_timezone({"timezone": "Mars/Olympus"}), timezone.utc)

    def test_missing_zone_falls_back_to_utc(self):
        self.assertEqual(_event_timezone({}), timezone.utc)


class TestBriefingWindow(unittest.TestCase):
    def test_real_booked_hours_are_used_as_is(self):
        m = meeting_ny()
        start, end, tz = _briefing_window(m)
        self.assertEqual(start, m["start_time_ms"])
        self.assertEqual(end, m["end_time_ms"])
        self.assertEqual(tz, NY)

    def test_missing_end_time_yields_no_window(self):
        m = meeting_ny(end=None)
        self.assertEqual(_briefing_window(m)[:2], (None, None))

    def test_end_before_start_yields_no_window(self):
        m = meeting_ny(start=(16, 0), end=(9, 0))
        self.assertEqual(_briefing_window(m)[:2], (None, None))

    def test_flat_24_hour_span_is_rejected_as_a_placeholder(self):
        base = datetime(2026, 3, 10, tzinfo=NY)
        m = {"timezone": "America/New_York", "start_time_ms": ms(base),
             "end_time_ms": ms(base + timedelta(days=1))}
        self.assertEqual(_briefing_window(m)[:2], (None, None))

    def test_multi_day_repeats_day_ones_clock_hours(self):
        m = meeting_ny()
        d2_start, d2_end, _ = _briefing_window(m, day_index=2)
        self.assertEqual(datetime.fromtimestamp(d2_start / 1000, tz=NY).day, 11)
        self.assertEqual(datetime.fromtimestamp(d2_start / 1000, tz=NY).hour, 8)
        self.assertEqual(datetime.fromtimestamp(d2_end / 1000, tz=NY).hour, 16)

    def test_canonical_13h_placeholder_is_rejected(self):
        # 07:00-20:00 is the placeholder span this data is full of. It is
        # exactly 13h, so a strict `> 13` let the very case the guard names
        # straight through.
        m = meeting_ny(start=(7, 0), end=(20, 0))
        self.assertEqual(_briefing_window(m)[:2], (None, None))

    def test_a_long_but_plausible_day_still_counts_as_booked(self):
        m = meeting_ny(start=(8, 0), end=(19, 0))  # 11h
        self.assertIsNotNone(_briefing_window(m)[0])


class TestFallbackWindow(unittest.TestCase):
    def test_uses_configured_day_hours_on_the_events_own_date(self):
        m = meeting_ny(end=None)
        start, end, tz = _fallback_window(m)
        s = datetime.fromtimestamp(start / 1000, tz=NY)
        e = datetime.fromtimestamp(end / 1000, tz=NY)
        self.assertEqual((s.year, s.month, s.day), (2026, 3, 10))
        self.assertEqual(s.hour * 60 + s.minute, _parse_clock(ag.AGENDA_DAY_START))
        self.assertEqual(e.hour * 60 + e.minute, _parse_clock(ag.AGENDA_DAY_END))


class TestScheduleSummary(unittest.TestCase):
    def test_booked_event_reports_its_real_hours(self):
        s = _schedule_summary(meeting_ny())
        self.assertTrue(s["booked"])
        self.assertEqual(s["minutes"], 480)
        self.assertEqual(s["date"], "Tuesday, 10 March 2026")
        self.assertIn("8:30 AM", s["label"])
        self.assertIn("4:30 PM", s["label"])
        self.assertNotIn("no booked hours", s["label"])

    def test_unbooked_event_says_so_in_the_label(self):
        s = _schedule_summary(meeting_ny(end=None))
        self.assertFalse(s["booked"])
        self.assertIn("no booked hours on file", s["label"])


class TestValidation(unittest.TestCase):
    def test_a_clean_day_inside_the_booked_window_passes(self):
        a = agenda_of(
            session("Welcome", "8:30 AM - 9:00 AM"),
            session("Strategy", "9:00 AM - 12:00 PM"),
            session("Lunch", "12:00 PM - 1:00 PM"),
            session("Next Steps", "1:00 PM - 1:30 PM"),
        )
        self.assertEqual(_validate_agenda_sessions(a, 1, meeting_ny()), [])

    def test_session_outside_the_booked_window_is_flagged(self):
        a = agenda_of(
            session("Early Bird", "7:00 AM - 8:00 AM"),
            session("Lunch", "12:00 PM - 1:00 PM"),
        )
        issues = _validate_agenda_sessions(a, 1, meeting_ny())
        self.assertTrue(any("starts before the day window" in i for i in issues))
        self.assertTrue(any("8:30 AM" in i for i in issues))

    def test_window_comes_from_the_booking_not_the_env_defaults(self):
        # 9:30 AM is inside the booked 8:30-4:30 day but before the 10:00 AM
        # env default — the old code flagged correct agendas like this one.
        a = agenda_of(
            session("Opening", "9:30 AM - 10:30 AM"),
            session("Lunch", "12:00 PM - 1:00 PM"),
        )
        self.assertEqual(_validate_agenda_sessions(a, 1, meeting_ny()), [])
        self.assertTrue(_validate_agenda_sessions(a, 1))  # env defaults: flagged

    def test_overlapping_sessions_are_flagged(self):
        a = agenda_of(
            session("A", "9:00 AM - 11:00 AM"),
            session("B", "10:00 AM - 11:30 AM"),
            session("Lunch", "12:00 PM - 1:00 PM"),
        )
        issues = _validate_agenda_sessions(a, 1, meeting_ny())
        self.assertTrue(any("overlaps the previous session" in i for i in issues))

    def test_missing_lunch_is_flagged(self):
        a = agenda_of(session("Strategy", "9:00 AM - 10:00 AM"))
        issues = _validate_agenda_sessions(a, 1, meeting_ny())
        self.assertTrue(any("No lunch break" in i for i in issues))

    def test_unparseable_slot_is_flagged(self):
        a = agenda_of(session("Strategy", "sometime after coffee"),
                      session("Lunch", "12:00 PM - 1:00 PM"))
        issues = _validate_agenda_sessions(a, 1, meeting_ny())
        self.assertTrue(any("unparseable time_slot" in i for i in issues))

    def test_multi_day_event_missing_a_day_is_flagged(self):
        a = agenda_of(session("Strategy", "9:00 AM - 10:00 AM"),
                      session("Lunch", "12:00 PM - 1:00 PM"))
        issues = _validate_agenda_sessions(a, 2, meeting_ny())
        self.assertTrue(any("day 2" in i.lower() for i in issues))


class TestSessionCountRange(unittest.TestCase):
    def test_a_standard_seven_hour_day_reproduces_the_old_range(self):
        self.assertEqual(_session_count_range(480), (6, 10))

    def test_a_half_day_asks_for_fewer_sessions(self):
        low, high = _session_count_range(240)
        self.assertEqual((low, high), (3, 5))

    def test_a_very_long_day_is_capped_per_day(self):
        low, high = _session_count_range(720)
        self.assertLessEqual(high, 10)
        self.assertLess(low, high)

    def test_a_long_multi_day_briefing_is_capped_in_total(self):
        # 12h x 3 days sized per-day worked out to 9-12 a day (up to 36) and
        # stalled generation outright.
        low, high = _session_count_range(720, num_days=3)
        self.assertLessEqual(high * 3, 24)
        self.assertLess(low, high)

    def test_a_standard_two_day_briefing_is_not_squeezed(self):
        self.assertEqual(_session_count_range(480, num_days=2), (6, 10))

    def test_no_window_falls_back_to_the_configured_range(self):
        self.assertEqual(_session_count_range(0),
                         (ag.AGENDA_SESSION_MIN, ag.AGENDA_SESSION_MAX))


class TestEventNumDays(unittest.TestCase):
    def test_reads_duration_and_clamps(self):
        self.assertEqual(_event_num_days({"duration_days": 3}), 3)
        self.assertEqual(_event_num_days({"duration_days": 99}), 5)
        self.assertEqual(_event_num_days({"duration_days": 0}), 1)
        self.assertEqual(_event_num_days({"duration_days": "junk"}), 1)
        self.assertEqual(_event_num_days(None), 1)


class TestScheduleAgendaSessions(unittest.TestCase):
    """Phase three: turn model durations into clock times on the booked day."""

    def _run(self, agenda, by_topic=None, conflicts=None, meeting=None):
        meeting = meeting or meeting_ny()
        with mock.patch("tools.presenter_suggest._check_presenter_conflicts",
                        return_value=conflicts or {}) as spy:
            summary = _schedule_agenda_sessions(
                agenda, {"meeting_details": meeting}, by_topic=by_topic or {}
            )
        return summary, spy

    def test_every_session_gets_a_slot_inside_the_booked_window(self):
        a = agenda_of(
            session("Welcome", duration=15),
            session("Strategy", duration=60),
            session("Lunch", duration=60),
            session("Next Steps", duration=15),
        )
        summary, _ = self._run(a)
        self.assertEqual(summary["scheduled"], 4)
        self.assertEqual(summary["did_not_fit"], [])
        self.assertTrue(a.sessions[0].time_slot.startswith("8:30 AM"))
        for s in a.sessions:
            start, end = _parse_time_slot(s.time_slot)
            self.assertGreaterEqual(start, 8 * 60 + 30)
            self.assertLessEqual(end, 16 * 60 + 30)

    def test_scheduled_agenda_passes_its_own_validator(self):
        a = agenda_of(
            session("Welcome", duration=15),
            session("Strategy", duration=90),
            session("Lunch", duration=60),
            session("Deep Dive", duration=90),
            session("Next Steps", duration=15),
        )
        self._run(a)
        self.assertEqual(_validate_agenda_sessions(a, 1, meeting_ny()), [])

    def test_sessions_are_left_in_chronological_order(self):
        a = agenda_of(*[session(f"S{i}", duration=45) for i in range(5)])
        self._run(a)
        starts = [_parse_time_slot(s.time_slot)[0] for s in a.sessions]
        self.assertEqual(starts, sorted(starts))

    def test_window_label_is_reported_for_each_day(self):
        a = agenda_of(session("Only", duration=30))
        summary, _ = self._run(a)
        self.assertEqual(len(summary["windows"]), 1)
        self.assertIn("8:30 AM", summary["windows"][0])

    def test_busy_presenter_is_scheduled_around(self):
        base = datetime(2026, 3, 10, tzinfo=NY)
        ada = {"presenter_name": "Ada Lovelace", "title": "Chief Architect",
               "email": "ada@x.com", "all_emails": ["ada@x.com"]}
        a = agenda_of(session("Strategy", duration=60, topic="Cloud Migration"))
        conflicts = {"ada@x.com": [{
            "start_ms": ms(base.replace(hour=8, minute=30)),
            "end_ms": ms(base.replace(hour=9, minute=0)),
        }]}
        summary, spy = self._run(a, by_topic={"Cloud Migration": [ada]},
                                 conflicts=conflicts)
        spy.assert_called_once()
        self.assertEqual(a.sessions[0].time_slot, "9:00 AM - 10:00 AM")
        self.assertIn("moved 30 min later", a.sessions[0].scheduling_note)
        self.assertEqual(summary["moved"][0].split(":")[0], "Strategy")

    def test_topic_winner_replaces_the_models_presenter(self):
        grace = {"presenter_name": "Grace Hopper", "title": "VP Engineering",
                 "email": "grace@x.com", "all_emails": ["grace@x.com"]}
        a = agenda_of(session("Strategy", duration=60, topic="Cloud Migration",
                              presenter="Someone Else — Analyst"))
        self._run(a, by_topic={"Cloud Migration": [grace]})
        self.assertEqual(a.sessions[0].presenter, "Grace Hopper — VP Engineering")
        self.assertEqual(a.sessions[0].presenter_before_topic_match,
                         "Someone Else — Analyst")

    def test_oversubscribed_day_reports_what_it_dropped(self):
        a = agenda_of(*[session(f"S{i}", duration=120) for i in range(6)])
        summary, _ = self._run(a)
        self.assertTrue(summary["did_not_fit"])
        self.assertEqual(len(a.sessions), summary["scheduled"])
        self.assertNotIn("", [s.time_slot for s in a.sessions])

    def test_multi_day_agenda_lays_out_each_day_separately(self):
        a = agenda_of(
            session("Day1 Open", day=1, duration=60),
            session("Day1 Lunch", day=1, duration=60),
            session("Day2 Open", day=2, duration=60),
            session("Day2 Lunch", day=2, duration=60),
        )
        summary, _ = self._run(a, meeting=meeting_ny(duration_days=2))
        self.assertEqual(summary["scheduled"], 4)
        self.assertEqual(len(summary["windows"]), 2)
        self.assertTrue(all(s.time_slot for s in a.sessions))

    def test_empty_agenda_is_a_no_op(self):
        a = agenda_of()
        summary, _ = self._run(a)
        self.assertEqual(summary, {"scheduled": 0})

    def test_availability_lookup_failure_still_produces_a_schedule(self):
        a = agenda_of(session("Strategy", duration=60, topic="Cloud Migration"))
        ada = {"presenter_name": "Ada", "email": "ada@x.com", "all_emails": ["ada@x.com"]}
        with mock.patch("tools.presenter_suggest._check_presenter_conflicts",
                        side_effect=RuntimeError("opensearch down")):
            summary = _schedule_agenda_sessions(
                a, {"meeting_details": meeting_ny()},
                by_topic={"Cloud Migration": [ada]},
            )
        self.assertEqual(summary["scheduled"], 1)
        self.assertTrue(a.sessions[0].time_slot)

    def test_unbooked_event_falls_back_to_default_hours(self):
        a = agenda_of(session("Strategy", duration=60))
        summary, _ = self._run(a, meeting=meeting_ny(end=None))
        self.assertIn("no booked hours on file", summary["windows"][0])
        self.assertTrue(a.sessions[0].time_slot.startswith(
            ag.AGENDA_DAY_START.replace(" AM", "").replace(" PM", "").lstrip("0")))

    def test_free_alternates_are_attached_as_backup_presenters(self):
        ada = {"presenter_name": "Ada", "title": "Chief Architect",
               "email": "ada@x.com", "all_emails": ["ada@x.com"]}
        grace = {"presenter_name": "Grace", "title": "VP Eng",
                 "email": "grace@x.com", "all_emails": ["grace@x.com"]}
        busy_alt = {"presenter_name": "Alan", "email": "alan@x.com",
                    "all_emails": ["alan@x.com"]}
        base = datetime(2026, 3, 10, tzinfo=NY)
        a = agenda_of(session("Strategy", duration=60, topic="Cloud Migration"))
        conflicts = {"alan@x.com": [{
            "start_ms": ms(base.replace(hour=8, minute=0)),
            "end_ms": ms(base.replace(hour=17, minute=0)),
        }]}
        summary, _ = self._run(a, by_topic={"Cloud Migration": [ada, grace, busy_alt]},
                               conflicts=conflicts)
        names = [b.presenter_name for b in a.sessions[0].backup_presenters]
        self.assertEqual(names, ["Grace"])          # Alan is busy, excluded
        self.assertEqual(a.sessions[0].backup_presenters[0].title, "VP Eng")
        self.assertEqual(summary["backups_offered"], 1)

    def test_sessions_without_candidates_get_no_backups(self):
        a = agenda_of(session("Lunch", duration=60))
        summary, _ = self._run(a)
        self.assertEqual(a.sessions[0].backup_presenters, [])
        self.assertEqual(summary["backups_offered"], 0)

    def test_this_events_own_bookings_are_excluded_from_the_busy_map(self):
        ada = {"presenter_name": "Ada", "email": "ada@x.com", "all_emails": ["ada@x.com"]}
        a = agenda_of(session("Strategy", duration=60, topic="Cloud Migration"))
        _, spy = self._run(a, by_topic={"Cloud Migration": [ada]})
        self.assertEqual(spy.call_args.kwargs["exclude_event_id"], "12345")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TruncationTests(unittest.TestCase):
    """The 4096-token ceiling that broke every multi-day briefing in prod.

    Converse applies a 4096 default when no inferenceConfig is sent, so the
    agenda object was cut off mid-JSON and pydantic blamed the fields that
    never arrived. These cover the cap going out, the truncation being named
    for what it is, and the retry asking for less instead of sending less.
    """

    def _tool_response(self, stop_reason="end_turn", out_tokens=3000):
        return {
            "stopReason": stop_reason,
            "usage": {"inputTokens": 5000, "outputTokens": out_tokens},
            "output": {"message": {"content": [{"toolUse": {
                "name": "emit_agenda", "input": {"unused": True},
            }}]}},
        }

    def test_max_tokens_is_sent_to_bedrock(self):
        """Without this the request silently inherits Converse's 4096 default."""
        seen = {}

        def fake_converse(**kwargs):
            seen.update(kwargs)
            return self._tool_response()

        with mock.patch.object(ag, "bedrock_converse", fake_converse), \
             mock.patch.object(ag.GeneratedAgenda, "model_validate", lambda d: "ok"):
            ag._call_llm_bedrock("sys", "user", [], [])

        self.assertEqual(seen.get("max_tokens"), ag.AGENDA_MAX_OUTPUT_TOKENS)
        self.assertGreater(ag.AGENDA_MAX_OUTPUT_TOKENS, 4096)

    def test_truncation_raises_agenda_truncated_not_validation_error(self):
        """stopReason=max_tokens must be named, not left to pydantic."""
        with mock.patch.object(
            ag, "bedrock_converse",
            lambda **kw: self._tool_response(stop_reason="max_tokens", out_tokens=16000),
        ):
            with self.assertRaises(ag.AgendaTruncated) as ctx:
                ag._call_llm_bedrock("sys", "user", [], [])
        self.assertIn("cut off", str(ctx.exception))

    def test_retry_after_truncation_asks_for_a_shorter_agenda(self):
        """Trimming the prompt cannot fix an output ceiling; the ask must shrink."""
        prompts = []

        def fake_converse(**kwargs):
            prompts.append(kwargs["messages"][0]["content"])
            if len(prompts) == 1:
                return self._tool_response(stop_reason="max_tokens", out_tokens=16000)
            return self._tool_response()

        with mock.patch.object(ag, "bedrock_converse", fake_converse), \
             mock.patch.object(ag.GeneratedAgenda, "model_validate", lambda d: "ok"):
            ag._call_llm_bedrock("sys", "## PREVIOUS MEETINGS\nx\n\n## OTHER\n", [], [])

        self.assertEqual(len(prompts), 2)
        self.assertNotIn("LENGTH CORRECTION", prompts[0])
        self.assertIn("LENGTH CORRECTION", prompts[1])
        self.assertIn("SHORTER", prompts[1])


class SessionCapEnforcementTests(unittest.TestCase):
    """Zurich was budgeted 20 sessions and wrote 35 — the prompt is advice."""

    def test_overlong_agenda_is_trimmed_to_the_cap(self):
        over = ag._MAX_SESSIONS_TOTAL + 11
        agenda = agenda_of(*[session(title=f"Session {i}") for i in range(over)])
        ag._enforce_session_cap(agenda)
        self.assertEqual(len(agenda.sessions), ag._MAX_SESSIONS_TOTAL)
        self.assertEqual(agenda.sessions[0].title, "Session 0")
        self.assertEqual(
            agenda.sessions[-1].title, f"Session {ag._MAX_SESSIONS_TOTAL - 1}"
        )

    def test_agenda_within_the_cap_is_left_alone(self):
        agenda = agenda_of(*[session(title=f"S{i}") for i in range(3)])
        ag._enforce_session_cap(agenda)
        self.assertEqual(len(agenda.sessions), 3)
