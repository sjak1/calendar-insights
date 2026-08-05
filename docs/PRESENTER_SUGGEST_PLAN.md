# Presenter Suggest — Design Notes

For `tools/presenter_suggest.py` (the `suggest_presenters` tool).

## How topic and presenter link

There is **no topic→presenter foreign key**. `activityData.topic[]` and
`activityData.topic_presenter[]` are sibling arrays inside one activity — "X
presented Y" means both appear in the same session record.

```
event  (a briefing)                     1 event : ~13-23 activities
 └─ activity  (1 topic : N presenters)
    ├─ topic[]           "Oracle RAC"
    └─ topic_presenter[] Priya (Accepted), Ana (Declined), Raj (Pending)
```

The 1:N is enforced upstream: the write API does
`PUT /forms/{TOPIC_FORM}/data/{activityId}` — an upsert, one topic per activity —
versus `POST /forms/{PRESENTER_FORM}/data` with `parentId`, which is unbounded.
Many-to-many ambiguity therefore cannot arise. `slotId` is a redundant copy of
`activityId` (identical in 100% of rows), so it is not used.

Presenters are identified by `presenter.uniqueId`, not email — a person can hold
several addresses, and calendar lookups search all of them.

## Ranking hierarchy

Tuple sort, each key breaking ties in the one above:

```
1. match_tier            exact > related > loose
2. tier_recent_weight    decayed sessions ON THAT TOPIC
3. tier_session_count    raw count on that topic
4. accepted_count
5. recent_weight         decayed sessions overall
6. event_count           distinct briefings (breadth)
7. latest_ts
```

With `audience_level`, three seniority keys slot in after (2): meets-tier →
C-level track record → seniority tier. Double-booked presenters are demoted
after ranking rather than inside the sort — a clashing presenter is still worth
showing, just not first.

**Recency decay**: each session is worth `0.5 ** (age / 365 days)`. Counting
every session equally meant someone who presented thirty times years ago
outranked someone active now. Decay rather than a cutoff, so long-serving
presenters fade gradually instead of vanishing the day they cross a line.

## Deliberately not ranked on

- **Opportunity revenue** — reported as context (`revenue_delta`,
  `revenue_note`), never scored. A briefing has several presenters and one
  revenue figure, so per-person credit is shared rather than earned, and large
  accounts draw senior presenters regardless — ranking on it would encode
  account size. Revisit only if a correlation shows up on real data.
- **Quality / success rate** — does not exist. No `rating|feedback|nps|survey`
  field in either index. `presenterStatus` is *invite response*, surfaced
  honestly as `accepted_count`. Real quality scoring needs capture on the
  presenter form first — product work, not ranking work.
- **Vector search** — the topic vocabulary is small (tens of entries) and
  `_available_topics` already hands the calling LLM the whole list, which judges
  product jargon better than a generic embedding model. Revisit past ~500
  topics, and then as a pre-filter feeding the LLM, never as a replacement for
  exact match.

## Test fixtures

- `scripts/seed_presenters.py` — 20 shaped activities: specialist-but-old vs
  recent-but-fewer (recency decay), exact vs phrase variant (tier ordering),
  low acceptance, sole owner, a same-hour double booking, and a token trap
  (*Cloud Kitchen Operations*, which shares "cloud" with the real vocabulary
  while being unrelated). Anchored to real event ids so customer scoping and
  revenue resolve. `--delete` removes exactly what it wrote.
- `scripts/seed_opp_revenue.py` — revenue figures across 8 events: increases,
  decreases, one flat, one closed-lost, one with no baseline. `--revert`
  restores originals from `.opp_revenue_backup.json`.
- `scripts/check_presenter_ranking.py` — 20 property assertions. Properties, not
  fixed orderings, so they survive index changes; they SKIP when fixtures are
  absent rather than failing.

## Gotchas worth knowing

- **The index gets rebuilt.** Activity counts, topic vocabulary and presenter
  rosters have all changed repeatedly. Trust live queries, never `os_dump/`.
- **Writes to `events` are not durable.** A source-system sync overwrote seeded
  revenue on one event between writing and reading it. Re-run and verify.
- **`EVENTS_VISIT_INFO` is an array** (one entry per opportunity), so revenue is
  summed across entries — taking `[0]` reports only the first deal.
- **Oracle is not used by this tool.** It holds presenter and topic views, but
  `UNIQUE_ID` there identifies an assignment row, not a person, and its revenue
  columns are empty. Do not port the identity assumption across.
