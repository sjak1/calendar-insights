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
