"""Tests for tools/presenter_suggest.py.

OpenSearch is mocked throughout — `search` is imported inside each function, so
patching `opensearch_client.search` covers every call path. What is exercised is
the ranking, the topic-match tiering, and the availability scans.
"""

import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tools.presenter_suggest as ps  # noqa: E402
from tools.presenter_suggest import (  # noqa: E402
    TIER_EXACT,
    TIER_PHRASE,
    TIER_SCOPE_ONLY,
    TIER_TOKENS,
    _check_presenter_conflicts,
    _classify_topic_match,
    _coerce_amount,
    _deep_get,
    _event_revenue,
    _extract_presenters_from_hits,
    _presenter_seniority,
    _rank_presenters,
    _recency_weight,
    _upcoming_load,
    get_suggested_presenters,
)

DAY_MS = 86400000
NOW = int(time.time() * 1000)


def activity(topics, presenters, event_id="e1", start_ms=None,
             booking_id="CBR-20260330-3625-031", zone_date="2026-03-30T09:00"):
    """One activities-index hit in the shape the extractor expects."""
    return {
        "id": event_id,
        "source": {
            "eventId": event_id,
            "bookingId": booking_id,
            "startTime": {
                "utcMs": start_ms if start_ms is not None else NOW,
                "requested": {"requestedZoneDate": zone_date},
            },
            "activityData": {
                "topic": [{"topic": {"textField1": t}} for t in topics],
                "topic_presenter": presenters,
            },
        },
    }


def presenter(first, last, email, title="Principal Architect",
              status="accepted", unique_id=None):
    return {
        "presenterStatus": status,
        "presenter": {
            "firstName": first, "lastName": last, "primaryEmail": email,
            "designation": title, "uniqueId": unique_id or "",
        },
    }


class TestTopicTiering(unittest.TestCase):
    def test_identical_topic_is_an_exact_match(self):
        self.assertEqual(_classify_topic_match("Cloud Migration", "cloud migration"),
                         TIER_EXACT)

    def test_contained_phrase_is_a_related_topic(self):
        self.assertEqual(_classify_topic_match("Big Data Appliance", "big data"),
                         TIER_PHRASE)

    def test_all_tokens_out_of_order_is_the_loosest_tier(self):
        self.assertEqual(_classify_topic_match("Migration to the Cloud", "cloud migration"),
                         TIER_TOKENS)

    def test_partial_word_overlap_does_not_match(self):
        self.assertEqual(_classify_topic_match("Cloud Kitchen Operations", "cloud computing"),
                         TIER_SCOPE_ONLY)

    def test_short_query_is_anchored_on_word_boundaries(self):
        # The regression this tiering exists to prevent: "ai" matching inside
        # "M-ai-ntenance" / "Tr-ai-ning".
        self.assertEqual(_classify_topic_match("Maintenance Strategy", "AI"), TIER_SCOPE_ONLY)
        self.assertEqual(_classify_topic_match("Training Programme", "ai"), TIER_SCOPE_ONLY)
        self.assertEqual(_classify_topic_match("AI Platform", "ai"), TIER_PHRASE)

    def test_empty_inputs_are_scope_only(self):
        self.assertEqual(_classify_topic_match("", "cloud"), TIER_SCOPE_ONLY)
        self.assertEqual(_classify_topic_match("Cloud", ""), TIER_SCOPE_ONLY)


class TestSeniority(unittest.TestCase):
    def test_chief_titles_are_top_tier(self):
        self.assertEqual(_presenter_seniority("Chief Technology Officer"), 3)
        self.assertEqual(_presenter_seniority("CFO"), 3)

    def test_vice_president_is_not_mistaken_for_president(self):
        self.assertEqual(_presenter_seniority("Vice President, Cloud"), 2)
        self.assertEqual(_presenter_seniority("President"), 3)

    def test_director_tier_and_default(self):
        self.assertEqual(_presenter_seniority("Head of Platform"), 1)
        self.assertEqual(_presenter_seniority("Solution Engineer"), 0)
        self.assertEqual(_presenter_seniority(""), 0)


class TestAmountCoercion(unittest.TestCase):
    def test_parses_formatted_currency(self):
        self.assertEqual(_coerce_amount("$1,200.50"), 1200.50)
        self.assertEqual(_coerce_amount(1200), 1200.0)
        self.assertEqual(_coerce_amount("-500"), -500.0)

    def test_unparseable_values_are_absent_not_fatal(self):
        for junk in (None, "", "   ", "n/a", "-", "."):
            self.assertIsNone(_coerce_amount(junk), junk)

    def test_bool_is_not_treated_as_a_number(self):
        self.assertIsNone(_coerce_amount(True))


class TestRecencyWeight(unittest.TestCase):
    def test_today_is_full_weight(self):
        self.assertAlmostEqual(_recency_weight(NOW, NOW), 1.0, places=3)

    def test_one_half_life_ago_is_half_weight(self):
        old = NOW - int(ps._RECENCY_HALF_LIFE_DAYS) * DAY_MS
        self.assertAlmostEqual(_recency_weight(old, NOW), 0.5, places=2)

    def test_future_bookings_do_not_outrank_delivered_sessions(self):
        self.assertEqual(_recency_weight(NOW + 30 * DAY_MS, NOW), 1.0)

    def test_missing_timestamp_is_zero(self):
        self.assertEqual(_recency_weight(None, NOW), 0.0)
        self.assertEqual(_recency_weight(0, NOW), 0.0)


class TestDeepGet(unittest.TestCase):
    def test_walks_and_stops_safely(self):
        self.assertEqual(_deep_get({"a": {"b": {"c": 1}}}, "a.b.c"), 1)
        self.assertIsNone(_deep_get({"a": 1}, "a.b"))
        self.assertIsNone(_deep_get(None, "a"))


class TestExtraction(unittest.TestCase):
    def test_declined_presenters_are_skipped(self):
        hits = [activity(["Cloud"], [
            presenter("Ada", "Lovelace", "ada@x.com"),
            presenter("Bob", "Bad", "bob@x.com", status="declined"),
        ])]
        out = _extract_presenters_from_hits(hits)
        self.assertEqual([p["presenter_name"] for p in out.values()], ["Ada Lovelace"])

    def test_one_person_two_addresses_is_a_single_entry(self):
        hits = [
            activity(["Cloud"], [presenter("Ada", "L", "ada@allianceit.com",
                                           unique_id="U1")], event_id="e1"),
            activity(["Cloud"], [presenter("Ada", "L", "ada@briefingiq.com",
                                           unique_id="U1")], event_id="e2"),
        ]
        out = _extract_presenters_from_hits(hits)
        self.assertEqual(len(out), 1)
        entry = next(iter(out.values()))
        self.assertEqual(entry["session_count"], 2)
        self.assertEqual(entry["emails"], {"ada@allianceit.com", "ada@briefingiq.com"})

    def test_strictest_tier_achieved_is_the_one_kept(self):
        hits = [
            activity(["Cloud Migration Planning"], [presenter("Ada", "L", "a@x.com")]),
            activity(["Cloud Migration"], [presenter("Ada", "L", "a@x.com")]),
        ]
        out = _extract_presenters_from_hits(hits, topic_query="Cloud Migration")
        entry = next(iter(out.values()))
        self.assertEqual(entry["match_tier"], TIER_EXACT)
        self.assertEqual(entry["matched_topic"], "Cloud Migration")
        self.assertEqual(entry["tier_session_count"], 1)
        self.assertEqual(entry["session_count"], 2)

    def test_records_with_neither_name_nor_email_are_ignored(self):
        hits = [activity(["Cloud"], [{"presenter": {}, "presenterStatus": "accepted"}])]
        self.assertEqual(_extract_presenters_from_hits(hits), {})


class TestRanking(unittest.TestCase):
    def _pool(self):
        exact = activity(["Cloud Migration"], [presenter("Exact", "One", "e@x.com")])
        loose = [activity(["Migration to the Cloud"],
                          [presenter("Loose", "Two", "l@x.com")]) for _ in range(5)]
        return _extract_presenters_from_hits([exact] + loose, topic_query="Cloud Migration")

    def test_one_exact_session_outranks_five_loose_ones(self):
        ranked = _rank_presenters(self._pool(), limit=10)
        self.assertEqual(ranked[0]["presenter_name"], "Exact One")
        self.assertEqual(ranked[0]["match_tier"], "exact match")

    def test_limit_is_honoured(self):
        self.assertEqual(len(_rank_presenters(self._pool(), limit=1)), 1)

    def test_reason_names_the_tier_and_the_matched_topic(self):
        top = _rank_presenters(self._pool(), limit=1)[0]
        self.assertIn("exact match: Cloud Migration", top["reason"])
        self.assertIn("session(s) total", top["reason"])

    def test_reason_never_claims_a_topic_match_when_there_was_no_filter(self):
        pool = _extract_presenters_from_hits(
            [activity(["Cloud"], [presenter("Ada", "L", "a@x.com")])])
        top = _rank_presenters(pool, limit=1)[0]
        self.assertEqual(top["match_tier"], "no topic filter")
        self.assertNotIn("exact match", top["reason"])


class TestSourceProvenance(unittest.TestCase):
    """The rows behind each candidate's counts, kept so the claim is checkable."""

    def _pool(self):
        return _extract_presenters_from_hits(
            [activity(["Cloud Migration"], [presenter("Ada", "L", "a@x.com")])],
            topic_query="Cloud Migration",
        )

    def test_ranked_output_carries_the_source_rows(self):
        top = _rank_presenters(self._pool(), limit=1)[0]
        row = top["source_activities"][0]
        self.assertEqual(row["booking_id"], "CBR-20260330-3625-031")
        self.assertEqual(row["event_id"], "e1")
        self.assertEqual(row["status"], "accepted")
        self.assertEqual(row["match_tier"], "exact match")

    def test_date_is_the_local_day_not_the_full_timestamp(self):
        top = _rank_presenters(self._pool(), limit=1)[0]
        self.assertEqual(top["source_activities"][0]["date"], "2026-03-30")

    def test_row_count_matches_the_session_count_it_explains(self):
        hits = [activity(["Cloud Migration"], [presenter("Ada", "L", "a@x.com")],
                         event_id=f"e{i}") for i in range(3)]
        top = _rank_presenters(
            _extract_presenters_from_hits(hits, topic_query="Cloud Migration"), limit=1
        )[0]
        self.assertEqual(top["session_count"], 3)
        self.assertEqual(len(top["source_activities"]), 3)

    def test_rows_are_capped_while_counts_stay_complete(self):
        # The cap is a display budget; it must not distort the numbers above it.
        hits = [activity(["Cloud Migration"], [presenter("Ada", "L", "a@x.com")],
                         event_id=f"e{i}") for i in range(20)]
        top = _rank_presenters(
            _extract_presenters_from_hits(hits, topic_query="Cloud Migration"), limit=1
        )[0]
        self.assertEqual(top["session_count"], 20)
        self.assertEqual(len(top["source_activities"]), 8)

    def test_declined_activities_never_appear_as_evidence(self):
        hits = [
            activity(["Cloud Migration"], [presenter("Ada", "L", "a@x.com")], event_id="kept"),
            activity(["Cloud Migration"],
                     [presenter("Ada", "L", "a@x.com", status="declined")], event_id="dropped"),
        ]
        top = _rank_presenters(
            _extract_presenters_from_hits(hits, topic_query="Cloud Migration"), limit=1
        )[0]
        self.assertEqual([r["event_id"] for r in top["source_activities"]], ["kept"])


class TestConflictScan(unittest.TestCase):
    def _hit(self, email, status="accepted", start=1000, end=2000):
        return {"source": {
            "eventId": "E9", "bookingId": "CBR-20260330-3625-031",
            "startTime": {"utcMs": start,
                          "requested": {"requestedZoneDate": "2026-03-30T10:00:00"}},
            "endTime": {"utcMs": end,
                        "requested": {"requestedZoneDate": "2026-03-30T11:00:00"}},
            "activityData": {"topic_presenter": [
                {"presenterStatus": status, "presenter": {"primaryEmail": email}}]},
        }}

    def test_overlapping_booking_is_reported_as_a_conflict(self):
        with mock.patch("opensearch_client.search",
                        return_value={"success": True, "hits": [self._hit("ada@x.com")]}):
            out = _check_presenter_conflicts(["ada@x.com"], 500, 1500)
        self.assertIn("ada@x.com", out)
        self.assertEqual(out["ada@x.com"][0]["time"], "10:00–11:00")
        self.assertEqual(out["ada@x.com"][0]["event_name"], "CBR-20260330-3625")

    def test_a_declined_slot_is_not_a_commitment(self):
        with mock.patch("opensearch_client.search",
                        return_value={"success": True,
                                      "hits": [self._hit("ada@x.com", status="declined")]}):
            self.assertEqual(_check_presenter_conflicts(["ada@x.com"], 500, 1500), {})

    def test_address_on_the_entry_rather_than_the_nested_object_still_counts(self):
        hit = {"source": {"eventId": "E9", "startTime": {"utcMs": 1000},
                          "endTime": {"utcMs": 2000},
                          "activityData": {"topic_presenter": [
                              {"presenterStatus": "accepted",
                               "presenterEmail": "ada@x.com"}]}}}
        with mock.patch("opensearch_client.search",
                        return_value={"success": True, "hits": [hit]}):
            out = _check_presenter_conflicts(["ada@x.com"], 500, 1500)
        self.assertIn("ada@x.com", out)

    def test_scan_is_not_silently_truncated_to_the_default_page_size(self):
        with mock.patch("opensearch_client.search",
                        return_value={"success": True, "hits": []}) as spy:
            _check_presenter_conflicts(["ada@x.com"], 500, 1500)
        self.assertEqual(spy.call_args.kwargs["size_cap"], ps._CONFLICT_SCAN_SIZE)
        self.assertEqual(spy.call_args.kwargs["body"]["size"], ps._CONFLICT_SCAN_SIZE)

    def test_excluded_event_goes_in_must_not_on_the_same_bool(self):
        with mock.patch("opensearch_client.search",
                        return_value={"success": True, "hits": []}) as spy:
            _check_presenter_conflicts(["ada@x.com"], 500, 1500, exclude_event_id="E1")
        bool_q = spy.call_args.kwargs["body"]["query"]["bool"]
        self.assertIn("must_not", bool_q)
        self.assertIn("must", bool_q)

    def test_failed_search_reports_no_conflicts_rather_than_raising(self):
        with mock.patch("opensearch_client.search",
                        return_value={"success": False, "error": "boom"}):
            self.assertEqual(_check_presenter_conflicts(["ada@x.com"], 500, 1500), {})

    def test_degenerate_window_is_rejected(self):
        self.assertEqual(_check_presenter_conflicts(["a@x.com"], 1500, 500), {})
        self.assertEqual(_check_presenter_conflicts([], 500, 1500), {})


class TestUpcomingLoad(unittest.TestCase):
    def _hit(self, email, day, status="accepted"):
        return {"source": {
            "startTime": {"utcMs": NOW, "requested": {"requestedZoneDate": f"{day}T09:00:00"}},
            "activityData": {"topic_presenter": [
                {"presenterStatus": status, "presenter": {"primaryEmail": email}}]},
        }}

    def test_booked_days_are_deduplicated(self):
        hits = [self._hit("ada@x.com", "2026-04-01"), self._hit("ada@x.com", "2026-04-01"),
                self._hit("ada@x.com", "2026-04-02")]
        with mock.patch("opensearch_client.search",
                        return_value={"success": True, "hits": hits}):
            out = _upcoming_load(["ada@x.com"])
        self.assertEqual(out["ada@x.com"], ["2026-04-01", "2026-04-02"])

    def test_declined_days_are_not_counted_as_load(self):
        with mock.patch("opensearch_client.search",
                        return_value={"success": True,
                                      "hits": [self._hit("ada@x.com", "2026-04-01",
                                                         status="declined")]}):
            self.assertEqual(_upcoming_load(["ada@x.com"]), {})


class TestEventRevenue(unittest.TestCase):
    def _hit(self, opps):
        return {"id": "E1", "source": {"eventFormData": {"EVENTS_VISIT_INFO": opps}}}

    def test_multiple_opportunities_are_summed(self):
        hit = self._hit([
            {"totalInitialOppRevenue": 100, "totalOppRevenue": 150},
            {"totalInitialOppRevenue": 200, "totalOppRevenue": 250},
        ])
        with mock.patch("opensearch_client.search",
                        return_value={"success": True, "hits": [hit]}):
            out = _event_revenue(["E1"])
        self.assertEqual(out["E1"]["initial"], 300.0)
        self.assertEqual(out["E1"]["latest"], 400.0)
        self.assertEqual(out["E1"]["delta"], 100.0)
        self.assertTrue(out["E1"]["has_baseline"])

    def test_closed_amount_wins_over_the_open_one(self):
        hit = self._hit([{"totalInitialOppRevenue": "1,000",
                          "totalOppRevenue": 900, "totalClosedOppRevenue": 0}])
        with mock.patch("opensearch_client.search",
                        return_value={"success": True, "hits": [hit]}):
            out = _event_revenue(["E1"])
        self.assertEqual(out["E1"]["latest"], 0.0)
        self.assertEqual(out["E1"]["delta"], -1000.0)

    def test_missing_baseline_is_flagged_not_invented(self):
        with mock.patch("opensearch_client.search",
                        return_value={"success": True,
                                      "hits": [self._hit([{"totalOppRevenue": 500}])]}):
            out = _event_revenue(["E1"])
        self.assertFalse(out["E1"]["has_baseline"])
        self.assertEqual(out["E1"]["delta"], 500.0)

    def test_no_ids_means_no_query(self):
        with mock.patch("opensearch_client.search") as spy:
            self.assertEqual(_event_revenue([]), {})
        spy.assert_not_called()


class TestPublicEntryPointValidation(unittest.TestCase):
    def test_at_least_one_filter_is_required(self):
        r = get_suggested_presenters()
        self.assertFalse(r["success"])
        self.assertIn("At least one filter", r["error"])

    def test_invalid_audience_level_is_rejected(self):
        r = get_suggested_presenters(topic="Cloud", audience_level="interns")
        self.assertFalse(r["success"])
        self.assertIn("Invalid audience_level", r["error"])

    def test_non_integer_limit_is_rejected(self):
        r = get_suggested_presenters(topic="Cloud", limit="lots")
        self.assertFalse(r["success"])
        self.assertIn("limit must be an integer", r["error"])

    def test_half_open_window_is_rejected_rather_than_silently_ignored(self):
        r = get_suggested_presenters(topic="Cloud", check_start_utc_ms=1000)
        self.assertFalse(r["success"])
        self.assertIn("must be given together", r["error"])

    def test_backwards_window_is_rejected(self):
        r = get_suggested_presenters(topic="Cloud", check_start_utc_ms=2000,
                                     check_end_utc_ms=1000)
        self.assertFalse(r["success"])
        self.assertIn("earlier than", r["error"])


class TestPublicEntryPointFlow(unittest.TestCase):
    def test_a_topic_nobody_has_presented_returns_guidance_not_loose_matches(self):
        def fake_search(index=None, body=None, **kw):
            if body.get("size") == 0:  # the diagnostic aggregations
                return {"success": True, "aggregations": {"topics": {"buckets": [
                    {"key": "Java Cloud"}, {"key": "Exadata"}]}}}
            return {"success": True, "hits": [], "total_hits": 0}

        with mock.patch("opensearch_client.search", side_effect=fake_search):
            r = get_suggested_presenters(topic="Quantum Teleportation")
        self.assertTrue(r["success"])
        self.assertEqual(r["suggested_presenters"], [])
        self.assertIn("No one has presented", r["message"])
        self.assertEqual(r["available_topics"], ["Java Cloud", "Exadata"])
        self.assertIn("Never describe these presenters", r["guidance"])

    def test_matching_topic_returns_ranked_presenters_with_forward_load(self):
        hits = [activity(["Cloud Migration"], [presenter("Ada", "L", "ada@x.com")])]

        def fake_search(index=None, body=None, **kw):
            if body.get("size") == 0:
                return {"success": True, "aggregations": {"topics": {"buckets": []}}}
            if "sort" in body and body.get("size") == 500:
                return {"success": True, "hits": hits, "total_hits": 1}
            return {"success": True, "hits": []}

        with mock.patch("opensearch_client.search", side_effect=fake_search):
            r = get_suggested_presenters(topic="Cloud Migration", limit=5)
        self.assertTrue(r["success"])
        top = r["suggested_presenters"][0]
        self.assertEqual(top["presenter_name"], "Ada L")
        self.assertEqual(top["match_tier"], "exact match")
        self.assertIn("no briefings booked in the next", top["availability_note"])

    def test_a_window_turns_the_answer_into_available_yes_or_no(self):
        hits = [activity(["Cloud Migration"], [presenter("Ada", "L", "ada@x.com")])]
        conflict_hit = {"source": {
            "eventId": "E9", "startTime": {"utcMs": 1200}, "endTime": {"utcMs": 1800},
            "activityData": {"topic_presenter": [
                {"presenterStatus": "accepted", "presenter": {"primaryEmail": "ada@x.com"}}]},
        }}

        def fake_search(index=None, body=None, **kw):
            if body.get("size") == 0:
                return {"success": True, "aggregations": {"topics": {"buckets": []}}}
            if body.get("size") == 500:
                return {"success": True, "hits": hits, "total_hits": 1}
            if kw.get("size_cap") == ps._CONFLICT_SCAN_SIZE:
                return {"success": True, "hits": [conflict_hit]}
            return {"success": True, "hits": []}

        with mock.patch("opensearch_client.search", side_effect=fake_search):
            r = get_suggested_presenters(topic="Cloud Migration",
                                         check_start_utc_ms=1000, check_end_utc_ms=2000)
        top = r["suggested_presenters"][0]
        self.assertFalse(top["available"])
        self.assertEqual(len(top["conflicts"]), 1)
        self.assertNotIn("upcoming_bookings", top)

    def test_limit_is_capped_at_the_hard_ceiling(self):
        seen = {}

        def fake_search(index=None, body=None, **kw):
            if body.get("size") == 0:
                return {"success": True, "aggregations": {"topics": {"buckets": []}}}
            seen["called"] = True
            return {"success": True, "hits": [], "total_hits": 0}

        with mock.patch("opensearch_client.search", side_effect=fake_search):
            r = get_suggested_presenters(topic="Cloud", limit=10_000)
        self.assertTrue(r["success"])
        self.assertLessEqual(len(r["suggested_presenters"]), ps._MAX_LIMIT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
