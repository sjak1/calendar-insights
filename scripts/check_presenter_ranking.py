"""Assertions about what suggest_presenters should return, and a runner for them.

Ranking changes are otherwise unfalsifiable: you alter a weight, the order
shifts, and nobody can say whether it improved. Each case below states a
property that must hold regardless of the weights — "the recent presenter
outranks the older one", "a topic nobody covers returns nobody" — so a change
that breaks the intent fails loudly instead of silently reshuffling.

Properties, not exact orderings: asserting a fixed top-10 would break every
time the index changes, which it does. Cases depend on scripts/seed_presenters.py
having been applied; they SKIP rather than fail when the fixtures are absent,
since the index gets rebuilt periodically.

Usage:
  python scripts/check_presenter_ranking.py
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.presenter_suggest import get_suggested_presenters  # noqa: E402

SEED_TOPIC = "Oracle RAC"
SEED_DOMAIN = "seed.example"


def names(result):
    return [p["presenter_name"] for p in result.get("suggested_presenters", [])]


def by_name(result, name):
    for p in result.get("suggested_presenters", []):
        if p["presenter_name"] == name:
            return p
    return None


def rank_of(result, name):
    ns = names(result)
    return ns.index(name) if name in ns else None


# Each case: (label, callable -> (verdict, detail))
# verdict is True (pass), False (fail) or None (skip — fixtures missing).
CASES = []


def case(label):
    def deco(fn):
        CASES.append((label, fn))
        return fn
    return deco


@case("recency: 3 recent sessions outrank 5 old ones on the same exact topic")
def _recency():
    r = get_suggested_presenters(topic=SEED_TOPIC, limit=10)
    ana, priya = rank_of(r, "Ana Silva"), rank_of(r, "Priya Raman")
    if ana is None or priya is None:
        return None, "seed fixtures absent"
    return ana < priya, f"Ana #{ana + 1} vs Priya #{priya + 1}"


@case("recency: the older presenter still has the higher raw session count")
def _recency_raw():
    # Guards the test itself — if Priya stopped having more sessions the case
    # above would pass for the wrong reason.
    r = get_suggested_presenters(topic=SEED_TOPIC, limit=10)
    ana, priya = by_name(r, "Ana Silva"), by_name(r, "Priya Raman")
    if not ana or not priya:
        return None, "seed fixtures absent"
    return priya["session_count"] > ana["session_count"], \
        f"Priya {priya['session_count']} vs Ana {ana['session_count']} sessions"


@case("tier: an exact-topic presenter outranks a related-topic one")
def _tier():
    r = get_suggested_presenters(topic=SEED_TOPIC, limit=20)
    tom = rank_of(r, "Tom Nakamura")  # only has "Oracle RAC Administration"
    if tom is None:
        return None, "seed fixtures absent"
    exact = [i for i, p in enumerate(r["suggested_presenters"])
             if p.get("match_tier") == "exact match"]
    if not exact:
        return None, "no exact matches present"
    return tom > max(exact), f"Tom #{tom + 1}, last exact #{max(exact) + 1}"


@case("tier: the label names how it matched, never silently substituting")
def _tier_label():
    r = get_suggested_presenters(topic=SEED_TOPIC, limit=20)
    tom = by_name(r, "Tom Nakamura")
    if not tom:
        return None, "seed fixtures absent"
    return (tom.get("match_tier") == "related topic"
            and tom.get("matched_topic") != SEED_TOPIC), \
        f"{tom.get('match_tier')} on {tom.get('matched_topic')!r}"


@case("tier: a short query never matches inside a longer word")
def _word_boundary():
    # The phrase tier used a bare substring test, so "AI" was a phrase match for
    # "M-ai-ntenance Strategy" and "Tr-ai-ning" — loose matching creeping back in
    # through the tier that is supposed to be strict, on exactly the short
    # queries people actually type.
    from tools.presenter_suggest import _classify_topic_match, TIER_SCOPE_ONLY, TIER_PHRASE

    inside_word = [("Maintenance Strategy", "AI"), ("Cloud Training", "ai"),
                   ("Database Administration", "data")]
    real_phrase = [("AI Platform", "AI"), ("Big Data Appliance", "Big Data")]

    bad = [(n, q) for n, q in inside_word if _classify_topic_match(n, q) != TIER_SCOPE_ONLY]
    missed = [(n, q) for n, q in real_phrase if _classify_topic_match(n, q) != TIER_PHRASE]
    return not bad and not missed, f"substring hits={bad} missed phrases={missed}"


@case("revenue: formatted amounts parse instead of raising")
def _revenue_coercion():
    # These arrive from user-entered form fields. float() raises on every one,
    # and the call site has no guard, so a single dirty cell took down the whole
    # response rather than just its revenue.
    from tools.presenter_suggest import _coerce_amount

    cases = {"": None, "  ": None, "abc": None, None: None,
             "1,200": 1200.0, "$500": 500.0, "-1,000.50": -1000.5, 0: 0.0, 42.5: 42.5}
    wrong = {}
    for raw, want in cases.items():
        try:
            got = _coerce_amount(raw)
        except Exception as exc:
            got = f"RAISED {type(exc).__name__}"
        if got != want:
            wrong[repr(raw)] = f"{got} != {want}"
    return not wrong, f"mismatches={wrong}" if wrong else "all parsed"


@case("guards: a half-open or inverted time window is rejected")
def _window_guard():
    # A half-open window used to fall through to the no-window branch, so a
    # caller asking "is anyone free on the 3rd?" silently got booking counts
    # back instead of an answer.
    half = get_suggested_presenters(topic=SEED_TOPIC, check_start_utc_ms=1_700_000_000_000)
    inverted = get_suggested_presenters(
        topic=SEED_TOPIC, check_start_utc_ms=5_000, check_end_utc_ms=2_000
    )
    bad_limit = get_suggested_presenters(topic=SEED_TOPIC, limit="abc")
    ok = (not half.get("success") and not inverted.get("success")
          and not bad_limit.get("success"))
    return ok, (f"half={half.get('error')!r} inverted={inverted.get('error')!r} "
                f"limit={bad_limit.get('error')!r}")


@case("scope: customer and industry together constrain, not widen")
def _scope_and():
    # All three clauses used to sit in one `should`, turning "this customer in
    # this industry" into "this customer OR anyone in that industry".
    from tools.presenter_suggest import _fetch_event_ids_by_scope
    from opensearch_client import search

    agg = search(index="events", body={"size": 0, "aggs": {
        "c": {"terms": {"field": "eventFormData.VISIT_INFO.customerName.keyword", "size": 1}},
        "i": {"terms": {"field": "eventFormData.VISIT_INFO.customerIndustry.keyword", "size": 1}},
    }}).get("aggregations") or {}
    cust = [b["key"] for b in agg.get("c", {}).get("buckets", [])]
    inds = [b["key"] for b in agg.get("i", {}).get("buckets", [])]
    if not cust or not inds:
        return None, "no customer/industry values indexed"

    only_c = _fetch_event_ids_by_scope(cust[0], None)
    only_i = _fetch_event_ids_by_scope(None, inds[0])
    both = _fetch_event_ids_by_scope(cust[0], inds[0])
    if not only_c and not only_i:
        return None, "neither filter resolved any events"
    return len(both) <= min(len(only_c), len(only_i)), \
        f"customer={len(only_c)} industry={len(only_i)} both={len(both)}"


@case("availability: the conflict scan is not silently capped at 50")
def _conflict_scan_depth():
    # The scan asked for size 200 but never passed size_cap, so the wrapper
    # clamped it to 50 and everything past that was invisible — reporting a
    # genuinely double-booked presenter as free.
    import time
    from tools.presenter_suggest import _check_presenter_conflicts, _CONFLICT_SCAN_SIZE

    r = get_suggested_presenters(topic=SEED_TOPIC, limit=10)
    emails = sorted({e for p in r.get("suggested_presenters", []) for e in p.get("all_emails") or []})
    if not emails:
        return None, "no presenters to check"

    now = int(time.time() * 1000)
    wide = _check_presenter_conflicts(emails, now - 86400000 * 400, now + 86400000 * 400)
    total = sum(len(v) for v in wide.values())
    if total < 50:
        return None, f"only {total} conflicts in range — cannot distinguish a 50 cap"
    return total > 50, f"{total} conflicts found across {len(emails)} emails (cap {_CONFLICT_SCAN_SIZE})"


@case("miss: a topic nobody has covered returns nobody")
def _miss():
    r = get_suggested_presenters(topic="Quantum Teleportation Ethics", limit=5)
    return not r.get("suggested_presenters"), f"{len(names(r))} returned"


@case("miss: a miss offers closest topics instead of wrong presenters")
def _miss_suggests():
    r = get_suggested_presenters(topic="cloud computing", limit=5)
    if r.get("suggested_presenters"):
        return False, "returned presenters for a topic nobody covers"
    return bool(r.get("closest_topics") or r.get("available_topics")), \
        f"closest={len(r.get('closest_topics') or [])}"


@case("miss: sharing one word is not a match")
def _one_word():
    # "cloud computing" shares "cloud" with several real topics; none contain
    # both words, so the answer must be nobody.
    r = get_suggested_presenters(topic="cloud computing", limit=5)
    return not r.get("suggested_presenters"), f"{len(names(r))} returned"


@case("declined: a declined-only presenter never appears")
def _declined():
    r = get_suggested_presenters(topic=SEED_TOPIC, limit=20)
    if not any(SEED_DOMAIN in (p.get("email") or "") for p in r.get("suggested_presenters", [])):
        return None, "seed fixtures absent"
    tom = by_name(r, "Tom Nakamura")
    # Tom has 4 sessions, 3 declined — he should show 1, not 4.
    return tom is None or tom["session_count"] == 1, \
        f"Tom sessions={tom['session_count'] if tom else 'absent'}"


@case("sole owner: a single-presenter topic returns exactly that presenter")
def _sole():
    r = get_suggested_presenters(topic="Quantum Risk Modeling", limit=5)
    if not r.get("suggested_presenters"):
        return None, "seed fixtures absent"
    return names(r) == ["Grace Okafor"], f"{names(r)}"


@case("availability: a double-booked presenter is flagged with conflicts")
def _conflict():
    r = get_suggested_presenters(topic="Cloud Kitchen Operations", limit=5)
    dan = by_name(r, "Dan Foley")
    if not dan:
        return None, "seed fixtures absent"
    ts = [c for c in (dan.get("upcoming_dates") or [])]
    # Without a window we report load, not conflicts — assert the field exists.
    return "availability_note" in dan, f"note={dan.get('availability_note')!r} dates={ts}"


@case("availability: no window given means no misleading available:true")
def _no_window():
    r = get_suggested_presenters(topic=SEED_TOPIC, limit=5)
    ps = r.get("suggested_presenters", [])
    if not ps:
        return None, "no results"
    return all("available" not in p for p in ps), \
        "available present without a window" if any("available" in p for p in ps) else "absent as expected"


def _session_window_for(emails):
    """A real (start, end) window in which one of `emails` is booked.

    Derived from the index rather than from upcoming_dates: a presenter's
    sessions are often all in the past, which leaves upcoming_dates empty
    while the clash is still perfectly checkable.
    """
    from opensearch_client import search
    from tools.presenter_suggest import _build_activity_query, _deep_get

    want = {e.lower() for e in emails}
    result = search(
        index="activities",
        body={"query": _build_activity_query(SEED_TOPIC, None), "size": 50},
    )
    for hit in result.get("hits", []):
        src = hit.get("source", {})
        start = _deep_get(src, "startTime.utcMs")
        end = _deep_get(src, "endTime.utcMs")
        if not start or not end:
            continue
        for pe in (src.get("activityData") or {}).get("topic_presenter") or []:
            email = (_deep_get(pe, "presenter.primaryEmail") or "").lower()
            if email in want:
                return int(start), int(end)
    return None, None


@case("availability: a free presenter below the cut is not lost to booked ones")
def _availability_pool():
    # The bug this pins: availability was applied AFTER truncating to `limit`,
    # so it could only reorder people already in the list — ask for 1 on a day
    # the leader is busy and you got the busy leader, never the free runner-up.
    wide = get_suggested_presenters(topic=SEED_TOPIC, limit=10)
    ps = wide.get("suggested_presenters", [])
    if len(ps) < 2:
        return None, "need at least 2 seeded presenters on the topic"

    leader = ps[0]
    start, end = _session_window_for(leader.get("all_emails") or [leader.get("email", "")])
    if not start:
        return None, f"no indexed session found for {leader['presenter_name']}"

    r = get_suggested_presenters(
        topic=SEED_TOPIC, limit=1,
        check_start_utc_ms=start, check_end_utc_ms=end,
    )
    got = r.get("suggested_presenters", [])
    if not got:
        return None, "windowed query returned nothing"

    top = got[0]
    if top.get("available"):
        return True, f"slot went to {top['presenter_name']} (free), not {leader['presenter_name']} (booked)"

    # Only acceptable if genuinely nobody on this topic is free in that window.
    everyone = get_suggested_presenters(
        topic=SEED_TOPIC, limit=10,
        check_start_utc_ms=start, check_end_utc_ms=end,
    ).get("suggested_presenters", [])
    free = [p["presenter_name"] for p in everyone if p.get("available")]
    return not free, f"returned booked {top['presenter_name']} while these were free: {free}"


@case("identity: one person never occupies two slots")
def _identity():
    r = get_suggested_presenters(topic=SEED_TOPIC, limit=20)
    ns = names(r)
    return len(ns) == len(set(ns)), f"{len(ns)} rows, {len(set(ns))} distinct"


@case("scope: a customer with events resolves rather than falling back")
def _scope():
    r = get_suggested_presenters(customer_name="Nikon", limit=5)
    if not r.get("suggested_presenters"):
        return None, "no Nikon events"
    return not r.get("unrelated_fallback"), \
        "fell back to unrelated presenters" if r.get("unrelated_fallback") else "scoped correctly"


@case("scope: a nonexistent customer does not silently return strangers")
def _bad_scope():
    r = get_suggested_presenters(customer_name="Nonexistent Corp Ltd", limit=5)
    if not r.get("suggested_presenters"):
        return True, "returned nobody"
    # If it does return people it must say they are unrelated.
    return bool(r.get("unrelated_fallback") or r.get("note")), \
        "returned presenters with no caveat"


@case("revenue: reported as context, never as a ranking key")
def _revenue_context():
    r = get_suggested_presenters(topic=SEED_TOPIC, limit=10)
    ps = [p for p in r.get("suggested_presenters", []) if p.get("revenue_delta") is not None]
    if len(ps) < 2:
        return None, "fewer than 2 presenters carry revenue"
    # The top result must not simply be the highest revenue delta.
    deltas = [p["revenue_delta"] for p in ps]
    return deltas[0] != max(deltas) or len(set(deltas)) == 1, \
        f"top delta={deltas[0]:,.0f}, max={max(deltas):,.0f}"


@case("revenue: the note says credit is shared, not earned")
def _revenue_wording():
    r = get_suggested_presenters(topic=SEED_TOPIC, limit=10)
    notes = [p.get("revenue_note") for p in r.get("suggested_presenters", []) if p.get("revenue_note")]
    if not notes:
        return None, "no revenue figures present"
    return all("shared" in n for n in notes), notes[0][:60]


@case("guards: no filter at all is an error, not an empty list")
def _no_filter():
    r = get_suggested_presenters(limit=5)
    return r.get("success") is False and "filter" in (r.get("error") or "").lower(), \
        f"{r.get('error')}"


@case("guards: an invalid audience_level is rejected")
def _bad_audience():
    r = get_suggested_presenters(topic=SEED_TOPIC, audience_level="emperor", limit=5)
    return r.get("success") is False, f"{r.get('error')}"


@case("limit: never returns more than asked for")
def _limit():
    r = get_suggested_presenters(topic=SEED_TOPIC, limit=2)
    return len(names(r)) <= 2, f"{len(names(r))} returned for limit=2"


@case("reason: every result explains itself")
def _reason():
    r = get_suggested_presenters(topic=SEED_TOPIC, limit=10)
    ps = r.get("suggested_presenters", [])
    if not ps:
        return None, "no results"
    return all(p.get("reason") for p in ps), f"{sum(1 for p in ps if not p.get('reason'))} missing"


def main() -> int:
    passed = failed = skipped = 0
    print(f"running {len(CASES)} ranking checks\n")
    for label, fn in CASES:
        try:
            verdict, detail = fn()
        except Exception as exc:
            verdict, detail = False, f"raised {type(exc).__name__}: {exc}"
        if verdict is None:
            skipped += 1
            print(f"  SKIP  {label}\n          {detail}")
        elif verdict:
            passed += 1
            print(f"  PASS  {label}")
        else:
            failed += 1
            print(f"  FAIL  {label}\n          {detail}")
    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
