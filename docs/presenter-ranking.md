# Presenter ranking — the priority order

How `suggest_presenters` decides who comes first.
Implemented in `_rank_presenters()` (`tools/presenter_suggest.py`).

## The rule

Results are sorted on a 7-part key. **The first part where two people differ
decides it — nothing below is looked at.** Not a weighted score, so there is no
trading off: a stronger topic match always beats more sessions.

| # | Signal | Meaning |
|---|--------|---------|
| 1 | **match tier** | exact > related > loosely related |
| 2 | **weighted depth on that topic** | sessions on the matched topic, aged |
| 3 | **session count on that topic** | raw count, as a tiebreak |
| 4 | **accepted count** | confirmed, not just invited |
| 5 | **weighted activity overall** | across all topics |
| 6 | **event coverage** | number of distinct briefings |
| 7 | **most recent session** | final tiebreak |

In practice most comparisons end at #1 or #2.

## Aging (#2 and #5)

Sessions are **weighted, not counted**:

```
weight = 0.5 ** (age_in_days / 365)
```

Full value today, half after a year, a quarter after two. A booked-but-not-yet-
delivered briefing counts a full 1.0 and no more.

Weights are **summed**, so volume and recency trade off predictably:

> **Doubling someone's session count buys one extra year of staleness.**

20 old sessions vs 2 recent ones: the veteran leads for ~3.3 years, then the
active presenter takes over. Decay rather than a cutoff, so nobody drops off a
cliff on a particular day.

## Applied after ranking, never inside it

**Availability** — with a date window, a wider pool is ranked first, availability
is checked across all of it, then the list is cut. Booked people are demoted, not
removed: a clash may still get resolved.

**Revenue** — reported as context only. A briefing has several presenters and one
revenue figure, so credit is shared rather than earned, and big accounts draw
senior presenters regardless. Ranking on it would mostly encode account size.

## Deliberately not ranked on

**Seniority.** An audience-peer tiebreak existed and is disabled. `designation`
put 410 of 433 records in one tier — a test almost everyone passes sorts nothing
— and where it did fire it ranked a CHRO above a Principal Cloud Architect for a
technical briefing. It measured rank, not role. The code is commented out in
`_rank_presenters` with the measurements.

## Who never appears

- Anyone whose entries are **all declined** on the matched activities.
- Anyone with **no session history at all** — presenters exist only inside
  activity documents today. (The `tenantresource` index holds the full roster
  and could close this.)

## Why it is a sort, not a score

A weighted score is unfalsifiable: change a coefficient, the order moves, and
nobody can say whether it improved. A tuple sort is deterministic and every
tiebreak is inspectable — you can point at the exact position that decided any
pair. `scripts/check_presenter_ranking.py` pins the intent with property checks
rather than fixed orderings.
