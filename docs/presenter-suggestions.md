# Presenter Suggestions — Deep Dive

How `suggest_presenters` decides who to recommend. Source:
[`tools/presenter_suggest.py`](../tools/presenter_suggest.py).

## What it does

You ask *"who should present?"* and it mines past activities to find people who
have **done it before**, then ranks them. It is rule logic over OpenSearch — no
ML. The guiding philosophy is **"return someone useful rather than nothing"**:
topic, audience, and seniority mostly *nudge* the ranking rather than hard-filter,
and there is an explicit fallback when a scoped search comes back empty.

## The flow

```
customer / industry ──► [events index] ──► event_ids
                                              │
topic + event_ids + audience ──► [activities index] ──► raw hits
                                              │
                                aggregate per presenter
                                              │
                                rank (audience seniority if asked)
                                              │
                                optional availability check
                                              │
                                        top N presenters
```

1. **Scope resolution** — `customer_name` / `industry` are resolved to a list of
   `event_ids` via the events index (`_fetch_event_ids_by_scope`): exact
   `.keyword` match (boosted) plus a fuzzy `match` for typo tolerance. An explicit
   `event_id` skips this step.
2. **Activity query** (`_build_activity_query`):
   - **must**: presenter email exists; activity belongs to one of the scoped events.
   - **should** (boost, not require): topic match (×3); C-level audience (×2).
   - `minimum_should_match: 1` is added **only** when there are no event_ids — i.e.
     topic becomes mandatory when it's the only filter you gave.
3. **Aggregate** (`_extract_presenters_from_hits`) — collapse many activities into
   one record per presenter (keyed by email, name fallback). Skips declined /
   cancelled. Tallies `session_count`, `accepted_count`, `c_level_session_count`,
   `topic_session_count`, distinct events, topics, recency, and a seniority tier.
4. **Rank** (`_rank_presenters`) — see below.
5. **Availability** (`_check_presenter_conflicts`) — only when the caller passes a
   time window. Flags anyone with an overlapping booking and lists the clashes.

## Ranking order

All sort keys are "best first." Topic relevance is a **leading** signal.

**No `audience_level`:**

1. On-topic session count
2. Accepted count
3. Total sessions
4. Distinct event coverage
5. Recency

**With `audience_level`** (`c_level` / `vp_plus` / `senior`):

1. Meets the seniority tier for the audience (peer-of-the-room gate)
2. On-topic session count
3. C-level audience track record (only for `c_level`)
4. Seniority tier
5. Accepted → sessions → coverage → recency

Seniority tiers are parsed from the presenter's title: Chief / President = 3,
VP/EVP/SVP = 2, Director / Head of / Managing = 1, everyone else = 0. "President"
only counts as tier 3 when it isn't part of "Vice President."

## How topic relevance works (and its limits)

- Topic is a **soft signal**, not a hard filter (except the only-filter case above).
- At retrieval, the activity search sorts by `["_score", startTime desc]` so the
  topic boost actually decides who survives the `size: 100` cap; recency only
  breaks ties. (Before this, a recency-only sort silently discarded the boost and
  could drop on-topic-but-older presenters before ranking.)
- Matching is **literal substring**, case-insensitive, both directions
  (`_topic_matches`): "cloud" matches "Cloud Security", but **not** "server".
- **Not** semantic — "server ≈ cloud" relatedness is not modelled. That would need
  a synonym map or embeddings / k-NN vector search, tracked separately.

## Output

Each suggestion includes `presenter_name`, `email`, `title`, `session_count`,
`event_count`, `c_level_session_count`, `topic_session_count`, `seniority_tier`,
a sample topic/event, and a human-readable `reason` string, e.g.
`"6 session(s) | 4 on-topic | 5 accepted | peer-level (CTO) | on: Cloud Security"`.
When an availability window is supplied, each also carries `available` and
`conflicts`.

## Fallback

If a scoped search (customer / industry / event_id) returns zero hits, it widens
to the most recent presenters overall so the caller still gets suggestions.
