"""
Presenter suggestion engine — queries OpenSearch activities index to find
presenters who have presented on matching topics or at matching events.
"""

import re
from typing import Any, Dict, List, Optional

from logging_config import get_logger

logger = get_logger(__name__)

ACTIVITIES_INDEX = "activities"
EVENTS_INDEX = "events"

# Activity index field paths (verified against live data — activityData.*, NOT
# the old empty activityInfo.* tree; the `.data` segment was also dropped).
TOPIC_NAME = "activityData.topic.topic.textField1"
PRESENTER_LIST = "activityData.topic_presenter"
PRESENTER_EMAIL_FIELD = "activityData.topic_presenter.presenter.primaryEmail"
# Unused: absent from all 311 activity docs. Kept as the verified path for
# whoever restores the audience-seniority work (see _rank_presenters).
ACT_IS_CLEVEL = "activityData.EVENTS_VISIT_INFO.isCLevelAttendee"
EVENT_ID = "eventId"
START_TIME = "startTime.utcMs"

# Events index field paths (rich form data now lives under eventFormData.*).
EVT_CUSTOMER_NAME = "eventFormData.VISIT_INFO.customerName"
EVT_CUSTOMER_INDUSTRY = "eventFormData.VISIT_INFO.customerIndustry"
EVT_EVENT_NAME = "eventFormData.VISIT_INFO.eventName"

# Opportunity revenue, per event. Reported as context on a presenter, never
# ranked on: a briefing has several presenters and one revenue figure, so any
# per-person credit is shared rather than earned, and large accounts draw
# senior presenters regardless — ranking on it would encode account size.
EVT_OPP_SECTION = "EVENTS_VISIT_INFO"
EVT_OPP_INITIAL = "totalInitialOppRevenue"
EVT_OPP_OPEN = "totalOppRevenue"
EVT_OPP_CLOSED = "totalClosedOppRevenue"

# Max events to pull when resolving customer/industry → event_ids
_MAX_SCOPE_EVENTS = 50

# How far ahead to report booked days when the caller gives no time window.
_LOOKAHEAD_DAYS = 30

# When a time window is given, rank this many times `limit` before checking
# availability, then cut to `limit` afterwards. Availability can only promote
# candidates it can see, so the pool has to be deeper than the answer.
_AVAILABILITY_POOL_FACTOR = 3

# Both availability scans fetch by time window and match presenters locally, so
# these caps bound how many briefings are examined — NOT how many presenters.
# They must be passed to search() as size_cap too: the body's "size" alone is
# clamped to _MAX_SIZE (50), and a truncated scan reports a booked presenter as
# free. Sized well above the busiest plausible window.
_CONFLICT_SCAN_SIZE = 1000
_LOAD_SCAN_SIZE = 1000

# Hard ceiling on results, whatever the caller asks for. The public entry point
# is reachable from an LLM tool call, so limit arrives as model-generated input.
_MAX_LIMIT = 50

# Half-life for weighting past sessions. Counting every session equally means
# someone who presented thirty times years ago outranks someone active now, so
# each session is worth 0.5 ** (age / half-life): full weight today, half at
# one half-life, a quarter at two. Decay rather than a cutoff, so a long-serving
# presenter fades gradually instead of vanishing the day they cross a line.
_RECENCY_HALF_LIFE_DAYS = 365.0

# Presenter statuses to exclude (don't suggest people who declined)
_EXCLUDED_STATUSES = {"declined", "rejected", "cancelled"}

# How closely a presenter's topic matched what was asked for. Retrieval runs the
# loosest STRICT tier (all-tokens) and each hit is then classified locally —
# exact ⊆ phrase ⊆ all-tokens, so one query returns the superset and the tier is
# a string comparison rather than three round trips.
#
# Any-token matching (the old behaviour) is deliberately NOT a tier: sharing one
# word is not evidence of having presented something. "cloud computing" matched
# "Cloud Kitchen Operations" that way, and nothing in the payload said so.
TIER_EXACT = 3
TIER_PHRASE = 2
TIER_TOKENS = 1
TIER_SCOPE_ONLY = 0

_TIER_LABELS = {
    TIER_EXACT: "exact match",
    TIER_PHRASE: "related topic",
    TIER_TOKENS: "loosely related topic",
    TIER_SCOPE_ONLY: "no topic filter",
}

# Audience-level signals
AUDIENCE_C_LEVEL = "c_level"
AUDIENCE_VP_PLUS = "vp_plus"
AUDIENCE_SENIOR = "senior"
_AUDIENCE_LEVELS = {AUDIENCE_C_LEVEL, AUDIENCE_VP_PLUS, AUDIENCE_SENIOR}

# Seniority tiers derived from presenter title. Higher = more senior.
# Tier 3: C-suite / President / Chief (but NOT "Vice President")
# Tier 2: VP / EVP / SVP
# Tier 1: Director / Head of / Managing
# Tier 0: everyone else
_VP_RE = re.compile(r"\bvice\s+president\b|\b[se]vp\b|\bvp\b", re.IGNORECASE)
_CHIEF_RE = re.compile(r"\b(ceo|cfo|cto|cio|coo|cmo|cxo|chief)\b", re.IGNORECASE)
_PRESIDENT_RE = re.compile(r"\bpresident\b", re.IGNORECASE)
_TIER1_RE = re.compile(r"\b(director|head\s+of|managing)\b", re.IGNORECASE)


def _presenter_seniority(title: str) -> int:
    """Rough seniority tier from a presenter's designation. Higher = more senior."""
    if not title:
        return 0
    t = title.lower()
    is_vp = bool(_VP_RE.search(t))
    # Tier 3 needs Chief/C-suite OR "President" that isn't part of "Vice President"
    if _CHIEF_RE.search(t) or (_PRESIDENT_RE.search(t) and not is_vp):
        return 3
    if is_vp:
        return 2
    if _TIER1_RE.search(t):
        return 1
    return 0


def _min_seniority_for_audience(audience_level: Optional[str]) -> int:
    """Minimum presenter seniority tier we consider a strong match for a given audience."""
    if audience_level == AUDIENCE_C_LEVEL:
        return 3
    if audience_level == AUDIENCE_VP_PLUS:
        return 2
    if audience_level == AUDIENCE_SENIOR:
        return 1
    return 0


def _recency_weight(ts_ms: Any, now_ms: int) -> float:
    """Weight for a session that happened at ts_ms. 1.0 today, 0.5 a half-life ago.

    Future-dated sessions (a booked briefing that has not happened yet) weigh a
    full 1.0 rather than more — being on the calendar is current evidence, but
    it should not outrank having actually delivered.
    """
    if not isinstance(ts_ms, (int, float)) or ts_ms <= 0:
        return 0.0
    age_days = (now_ms - ts_ms) / 86400000.0
    if age_days <= 0:
        return 1.0
    return 0.5 ** (age_days / _RECENCY_HALF_LIFE_DAYS)


def _classify_topic_match(topic_name: str, query: str) -> int:
    """How strictly `topic_name` satisfies `query`. Higher = stricter.

    Mirrors what OpenSearch would score, but locally, so retrieval stays a
    single request. Topic names are short (median 2 words) which is why a
    phrase test stands in for match_phrase here.

    The phrase test is anchored on word boundaries, not a bare substring: `in`
    made "AI" a phrase match for "M-ai-ntenance Strategy" and "Tr-ai-ning",
    silently reintroducing the loose matching that tiering exists to prevent.
    Short queries are exactly the ones users type, so the bug hit the common
    case hardest.
    """
    if not topic_name or not query:
        return TIER_SCOPE_ONLY
    name = topic_name.strip().lower()
    q = query.strip().lower()
    if name == q:
        return TIER_EXACT
    # \b on each end: "big data" still matches "big data appliance", but "ai"
    # no longer matches inside another word.
    if re.search(rf"\b{re.escape(q)}\b", name):
        return TIER_PHRASE
    q_tokens = set(re.findall(r"[a-z0-9]+", q))
    name_tokens = set(re.findall(r"[a-z0-9]+", name))
    if q_tokens and q_tokens <= name_tokens:
        return TIER_TOKENS
    return TIER_SCOPE_ONLY


def _closest_topics(index: str, topic: str, limit: int = 12) -> List[str]:
    """Topic names sharing any word with `topic` — suggestions, not results.

    This is the old any-token query, demoted to what it is actually good for:
    telling the caller which real topics are in the neighbourhood of a miss,
    instead of passing off their presenters as matches for what was asked.
    """
    body = {
        "query": {"match": {TOPIC_NAME: topic}},
        "size": 0,
        "aggs": {"topics": {"terms": {"field": f"{TOPIC_NAME}.keyword", "size": limit}}},
    }
    try:
        from opensearch_client import search

        result = search(index=index, body=body)
        if not result.get("success"):
            return []
        buckets = (result.get("aggregations") or {}).get("topics", {}).get("buckets", [])
        return [b["key"] for b in buckets if b.get("key")]
    except Exception as exc:
        logger.warning(f"closest-topics lookup failed: {exc}")
        return []


def _coerce_amount(value: Any) -> Optional[float]:
    """Parse a revenue figure that may arrive as a formatted string.

    These come from user-entered form fields, so alongside real numbers you get
    "", "1,200", "$500" and None. A bare float() raises on every one of those,
    and the call sites sit in the main path with no guard — so one dirty cell
    took down the whole presenter response, not just its revenue.

    Returns None for anything unparseable, which callers already treat as
    "no figure recorded".
    """
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    # Strip currency symbols, thousands separators and spaces; keep sign and point.
    cleaned = re.sub(r"[^0-9.\-]", "", text)
    if not cleaned or cleaned in {"-", ".", "-."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        logger.warning(f"Unparseable revenue value {value!r}; treated as absent")
        return None


def _deep_get(d: Any, path: str) -> Any:
    """Retrieve a nested value from a dict using dot-separated path."""
    for key in path.split("."):
        if isinstance(d, dict):
            d = d.get(key)
        else:
            return None
    return d


def _fetch_event_ids_by_scope(
    customer_name: Optional[str],
    industry: Optional[str],
) -> List[str]:
    """
    Query the events index for events matching customer or industry.
    Returns up to _MAX_SCOPE_EVENTS event_ids.
    """
    try:
        from opensearch_client import search
    except ImportError:
        return []

    # Industry goes in `must` (required), the two customer-name variants go in
    # `should` with minimum_should_match=1 (either spelling will do). Together
    # that reads: industry AND (exact name OR fuzzy name) — so asking for a
    # customer in an industry requires both. Previously all three sat in one
    # `should`, which turned it into "this customer OR anyone in that industry".
    #
    # Deliberately a FLAT bool rather than one nested per filter: the shared
    # client's normalize_query_structure() unwraps `bool` objects found inside
    # a must/should list, so a nested form arrives at OpenSearch malformed.
    must: List[Dict[str, Any]] = []
    should: List[Dict[str, Any]] = []

    if industry:
        must.append(
            {"term": {f"{EVT_CUSTOMER_INDUSTRY}.keyword": {"value": industry, "boost": 2}}}
        )
    if customer_name:
        should.append(
            {"term": {f"{EVT_CUSTOMER_NAME}.keyword": {"value": customer_name, "boost": 3}}}
        )
        should.append(
            {"match": {EVT_CUSTOMER_NAME: {"query": customer_name, "fuzziness": "AUTO"}}}
        )

    if not must and not should:
        return []

    bool_q: Dict[str, Any] = {}
    if must:
        bool_q["must"] = must
    if should:
        bool_q["should"] = should
        bool_q["minimum_should_match"] = 1

    body = {
        "query": {"bool": bool_q},
        "_source": False,
        "size": _MAX_SCOPE_EVENTS,
    }

    result = search(index=EVENTS_INDEX, body=body)
    if not result.get("success"):
        logger.warning(f"Event scope lookup failed: {result.get('error')}")
        return []

    event_ids = [h.get("id") for h in result.get("hits", []) if h.get("id")]
    logger.info(
        f"Scope lookup: customer={customer_name}, industry={industry} → {len(event_ids)} events"
    )
    return event_ids


def _available_topics(index: str, limit: int = 40) -> List[str]:
    """
    The topic names that actually exist in presenter history, most-covered first.

    Returned alongside an empty topic search so the caller can see the real
    vocabulary instead of guessing. Topic matching is lexical, so a topic the
    tenant has no wording for (e.g. "AI" against a catalogue of "Java Cloud",
    "Exadata Cloud at Customer") matches nothing — and the agent, given only
    "0 results", tends to retry with progressively vaguer terms and then
    present whatever finally returns as though it matched the original ask.
    """
    body = {
        "size": 0,
        "aggs": {"topics": {"terms": {"field": f"{TOPIC_NAME}.keyword", "size": limit}}},
    }
    try:
        from opensearch_client import search

        result = search(index=index, body=body)
        if not result.get("success"):
            return []
        buckets = (
            (result.get("aggregations") or {}).get("topics", {}).get("buckets", [])
        )
        return [b["key"] for b in buckets if b.get("key")]
    except Exception as exc:  # never let a diagnostic aggregation break the tool
        logger.warning(f"available-topics lookup failed: {exc}")
        return []


def _build_activity_query(
    topic: Optional[str],
    event_ids: Optional[List[str]],
) -> Dict[str, Any]:
    """Build OpenSearch query for the activities index.

    Retrieval only — nothing here influences order. `_score` is never read;
    ranking is a plain sort in _rank_presenters, so a `should` clause would
    move a number nobody consumes. audience_level is therefore ignored (it
    once added a C-level boost; see the note in _rank_presenters).
    """
    must: List[Dict[str, Any]] = [
        {"exists": {"field": PRESENTER_EMAIL_FIELD}},
    ]

    if event_ids:
        must.append({"terms": {f"{EVENT_ID}.keyword": event_ids}})

    if topic:
        # operator:and — every word must be present. The default (OR) is what
        # returned "Cloud Kitchen Operations" for "cloud computing".
        must.append({"match": {TOPIC_NAME: {"query": topic, "operator": "and"}}})

    return {"bool": {"must": must}}


def _extract_presenters_from_hits(
    hits: List[Dict[str, Any]],
    topic_query: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Aggregate presenters from activity hits. Iterates the topic_presenter array
    per activity and skips declined entries.

    When topic_query is given, each activity's topic is classified into a match
    tier and the presenter keeps the STRICTEST tier they achieved — someone with
    one exact-topic session outranks someone with five loose ones.
    """
    import time as _time

    now_ms = int(_time.time() * 1000)
    presenters: Dict[str, Dict[str, Any]] = {}

    for hit in hits:
        src = hit.get("source", {})
        activity_data = src.get("activityData") or {}
        presenter_entries = activity_data.get("topic_presenter") or []
        topic_entries = activity_data.get("topic") or []

        # Collect topic names for this activity
        topic_names: List[str] = []
        for t in topic_entries:
            name = _deep_get(t, "topic.textField1")
            if name and name not in topic_names:
                topic_names.append(name)
        # Strictest tier any of this activity's topics achieves, plus the topic
        # name that earned it — so the reason can name what actually matched
        # rather than whichever topic happened to sort first.
        activity_tier = TIER_SCOPE_ONLY
        tier_topic = ""
        if topic_query:
            for name in topic_names:
                t = _classify_topic_match(name, topic_query)
                if t > activity_tier:
                    activity_tier, tier_topic = t, name

        primary_topic = tier_topic or (topic_names[0] if topic_names else "")

        # Did this activity have a C-level audience? Field is on
        # activityData.EVENTS_VISIT_INFO[].isCLevelAttendee (array).
        visit_infos = activity_data.get("EVENTS_VISIT_INFO") or []
        is_c_level_audience = any(
            bool(_deep_get(v, "isCLevelAttendee")) for v in visit_infos
        )

        eid = src.get("eventId") or ""
        ts = _deep_get(src, START_TIME) or 0
        weight = _recency_weight(ts, now_ms)

        for p_entry in presenter_entries:
            # Each topic_presenter entry IS the data object (no nested `.data`).
            presenter = p_entry.get("presenter") or {}
            status = (p_entry.get("presenterStatus") or "").strip().lower()

            if status in _EXCLUDED_STATUSES:
                continue

            first = (presenter.get("firstName") or "").strip()
            last = (presenter.get("lastName") or "").strip()
            full_name = f"{first} {last}".strip()
            email = (presenter.get("primaryEmail") or p_entry.get("presenterEmail") or "").strip()
            title = (presenter.get("designation") or p_entry.get("presenterTitle") or "").strip()

            if not full_name and not email:
                continue

            # Key on BriefingIQ's own person id, not the email — the same person
            # can hold more than one address (all 5 live presenters carry both an
            # @allianceit.com and an @briefingiq.com one, sharing a uniqueId), and
            # keying on email splits their history and fills two slots in the
            # same top-N. Email/name remain fallbacks for records without an id.
            unique_id = (presenter.get("uniqueId") or "").strip().lower()
            key = unique_id or email.lower() or full_name.lower()
            if key not in presenters:
                presenters[key] = {
                    "presenter_name": full_name or email,
                    # Original-case uniqueId — the dedupe key above is lowercased,
                    # but BriefingIQ resource lookups need it exactly as issued.
                    "presenter_id": (presenter.get("uniqueId") or "").strip(),
                    "email": email,
                    "title": title,
                    "session_count": 0,
                    "event_ids": set(),
                    "topics": [],
                    "latest_ts": 0,
                    "sample_topic": "",
                    "sample_event_id": "",
                    "accepted_count": 0,
                    "c_level_session_count": 0,
                    "seniority_tier": _presenter_seniority(title),
                    "match_tier": TIER_SCOPE_ONLY,
                    "matched_topic": "",
                    "tier_session_count": 0,
                    # Every address this person appears under. Deduping on
                    # uniqueId means `email` holds only whichever came first,
                    # so calendar lookups must search all of them or they miss
                    # bookings filed under the other address.
                    "emails": set(),
                    "recent_weight": 0.0,
                    "tier_recent_weight": 0.0,
                }

            entry = presenters[key]
            entry["session_count"] += 1
            entry["recent_weight"] += weight
            if email:
                entry["emails"].add(email.lower())
            if activity_tier > entry["match_tier"]:
                entry["match_tier"] = activity_tier
                entry["matched_topic"] = tier_topic
                entry["tier_session_count"] = 1
                entry["tier_recent_weight"] = weight
            elif activity_tier == entry["match_tier"] and activity_tier > TIER_SCOPE_ONLY:
                entry["tier_session_count"] += 1
                entry["tier_recent_weight"] += weight
            if status == "accepted":
                entry["accepted_count"] += 1
            if is_c_level_audience:
                entry["c_level_session_count"] += 1
            if eid:
                entry["event_ids"].add(eid)
            for tn in topic_names:
                if tn not in entry["topics"]:
                    entry["topics"].append(tn)
            if isinstance(ts, (int, float)) and ts > entry["latest_ts"]:
                entry["latest_ts"] = ts
                entry["sample_topic"] = primary_topic
                entry["sample_event_id"] = eid
            if not entry["title"] and title:
                entry["title"] = title
                entry["seniority_tier"] = _presenter_seniority(title)
            if not entry["email"] and email:
                entry["email"] = email

    return presenters


def _rank_presenters(
    presenters: Dict[str, Dict[str, Any]],
    limit: int,
    audience_level: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Rank presenters.

    Order: topic match tier → decay-weighted depth on that topic → accepted →
    recency → event coverage.

    Seniority/audience-peer ranking is DISABLED — see the note below.
    """

    def sort_key(p: Dict[str, Any]):
        # 1. Match strength leads — an exact-topic presenter outranks a
        #    related-topic one regardless of volume.
        # 2. Then decay-weighted depth ON THAT TOPIC. Weighted, not counted, so
        #    a burst of old sessions loses to steady recent ones; rounded so
        #    near-identical weights fall through to the later keys rather than
        #    being separated by floating-point noise.
        match = (
            -p.get("match_tier", TIER_SCOPE_ONLY),
            -round(p.get("tier_recent_weight", 0.0), 3),
            -p.get("tier_session_count", 0),
        )
        # DISABLED: audience-peer tiebreak (seniority_tier + c_level_session_count).
        # Both inputs are unusable on the current data:
        #   - designation puts 410 of 433 presenter records in the top tier, so
        #     the test is one nearly everyone passes and sorts nothing; where it
        #     does fire it ranks a CHRO above a Principal Cloud Architect for a
        #     technical briefing, because it measures rank and not role.
        #   - isCLevelAttendee is absent from all 311 activity docs, so
        #     c_level_session_count is always 0.
        # Restore only alongside a role-type classifier (architect / solution
        # engineer / product) and a populated audience-seniority field.
        #
        # if audience_level:
        #     min_tier = _min_seniority_for_audience(audience_level)
        #     meets_tier = 1 if p["seniority_tier"] >= min_tier else 0
        #     return match + (
        #         -meets_tier,
        #         -p["c_level_session_count"] if audience_level == AUDIENCE_C_LEVEL else 0,
        #         -p["seniority_tier"],
        #         -p["accepted_count"],
        #         -round(p.get("recent_weight", 0.0), 3),
        #         -len(p["event_ids"]),
        #         -p["latest_ts"],
        #     )
        return match + (
            -p["accepted_count"],
            -round(p.get("recent_weight", 0.0), 3),
            -len(p["event_ids"]),
            -p["latest_ts"],
        )

    ranked = sorted(presenters.values(), key=sort_key)

    results = []
    for p in ranked[:limit]:
        tier = p.get("match_tier", TIER_SCOPE_ONLY)
        # Don't restate the matched topic in the topic list — when it's their
        # only one the reason would otherwise name it twice.
        other_topics = [t for t in p["topics"] if t != p.get("matched_topic")]
        topics_summary = ", ".join(other_topics[:3])
        if len(other_topics) > 3:
            topics_summary += f" (+{len(other_topics) - 3} more)"
        reason_parts = []
        if tier > TIER_SCOPE_ONLY and p.get("matched_topic"):
            # Lead with how well they matched — an agent skimming the reason
            # must not be able to mistake "related" for "exact".
            reason_parts.append(f"{_TIER_LABELS[tier]}: {p['matched_topic']}")
            if p.get("tier_session_count"):
                reason_parts.append(f"{p['tier_session_count']} session(s) on it")
        reason_parts.append(f"{p['session_count']} session(s) total")
        if p["accepted_count"]:
            reason_parts.append(f"{p['accepted_count']} accepted")
        # No "peer-level" / "C-level audience" claims while the seniority
        # tiebreak is disabled — the reason must describe what actually ranked.
        if topics_summary:
            label = "also presents" if tier > TIER_SCOPE_ONLY else "on"
            reason_parts.append(f"{label}: {topics_summary}")
        results.append(
            {
                "presenter_name": p["presenter_name"],
                "presenter_id": p.get("presenter_id", ""),
                "email": p["email"],
                "title": p["title"],
                "session_count": p["session_count"],
                "event_count": len(p["event_ids"]),
                "c_level_session_count": p["c_level_session_count"],
                "seniority_tier": p["seniority_tier"],
                "match_tier": _TIER_LABELS[p.get("match_tier", TIER_SCOPE_ONLY)],
                "matched_topic": p.get("matched_topic", ""),
                "tier_session_count": p.get("tier_session_count", 0),
                "recency_weighted_sessions": round(p.get("recent_weight", 0.0), 2),
                "all_emails": sorted(p["emails"]),
                "event_ids": sorted(p["event_ids"]),
                "sample_topic": p["sample_topic"],
                "sample_event_id": p["sample_event_id"],
                "sample_event_name": "",
                "reason": " | ".join(reason_parts),
            }
        )
    return results


def _check_presenter_conflicts(
    presenter_emails: List[str],
    check_start_ms: int,
    check_end_ms: int,
    exclude_event_id: Optional[str] = None,
) -> Dict[str, List[Dict]]:
    """Check which presenters have overlapping activities in the given window.

    Classic overlap condition: activity starts before our window ends
    AND activity ends after our window starts.

    Returns dict keyed by email → list of conflict dicts:
      {"event_id", "event_name", "start_ms", "end_ms", "start_time_local", "end_time_local"}
    """
    try:
        from opensearch_client import search
    except ImportError:
        return {}

    if not presenter_emails or check_start_ms >= check_end_ms:
        return {}

    must: List[Dict] = [
        {"range": {"startTime.utcMs": {"lt": check_end_ms}}},
        {"range": {"endTime.utcMs": {"gt": check_start_ms}}},
    ]
    if exclude_event_id:
        must.append({"bool": {"must_not": [{"term": {"eventId.keyword": exclude_event_id}}]}})

    body = {
        "query": {"bool": {"must": must}},
        "_source": [
            "eventId", "bookingId",
            "startTime.utcMs", "endTime.utcMs",
            "startTime.requested.requestedZoneDate",
            "endTime.requested.requestedZoneDate",
            PRESENTER_LIST,
        ],
        "size": _CONFLICT_SCAN_SIZE,
    }

    # Explicit size_cap: search() otherwise clamps to _MAX_SIZE (50). A busy
    # window holds far more than 50 briefings, and the ones past the cut are
    # simply not seen — which reports a genuinely double-booked presenter as
    # available. Under-reporting a clash is the worst failure this function has.
    result = search(index=ACTIVITIES_INDEX, body=body, size_cap=_CONFLICT_SCAN_SIZE)
    if not result.get("success"):
        logger.warning(f"Availability check failed: {result.get('error')}")
        return {}

    email_set = {e.lower() for e in presenter_emails}
    conflicts: Dict[str, List[Dict]] = {}

    for hit in result.get("hits", []):
        src = hit.get("source", {})
        presenter_entries = (src.get("activityData") or {}).get("topic_presenter") or []
        for pe in presenter_entries:
            # Someone who declined this briefing is not committed to it, so it
            # is not a clash. Without this, declining a slot made a presenter
            # look busy for it — marking free people unavailable.
            if (pe.get("presenterStatus") or "").strip().lower() in _EXCLUDED_STATUSES:
                continue
            # Same fallback the extraction side uses: a record may carry the
            # address on the entry rather than the nested presenter object, and
            # checking only one of the two silently misses that person's clashes.
            email = (
                _deep_get(pe, "presenter.primaryEmail") or pe.get("presenterEmail") or ""
            )
            if email.lower() not in email_set:
                continue
            start_ms = _deep_get(src, "startTime.utcMs") or 0
            end_ms = _deep_get(src, "endTime.utcMs") or 0
            start_local = _deep_get(src, "startTime.requested.requestedZoneDate") or ""
            end_local = _deep_get(src, "endTime.requested.requestedZoneDate") or ""
            if start_local and "T" in start_local:
                start_local = start_local.split("T")[1][:5]
            if end_local and "T" in end_local:
                end_local = end_local.split("T")[1][:5]
            # bookingId e.g. "CBR-20260330-3625-031" → strip last segment for display
            booking_id = src.get("bookingId", "")
            event_label = "-".join(booking_id.split("-")[:3]) if booking_id else src.get("eventId", "")[:8]
            conflicts.setdefault(email.lower(), []).append({
                "event_id": src.get("eventId", ""),
                "event_name": event_label,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "time": f"{start_local}–{end_local}" if start_local else "unknown time",
            })

    logger.info(
        f"Availability check: {len(presenter_emails)} presenters, window {check_start_ms}-{check_end_ms}, "
        f"{len(conflicts)} with conflicts"
    )
    return conflicts


def _upcoming_load(
    presenter_emails: List[str],
    lookahead_days: int = 30,
) -> Dict[str, List[str]]:
    """Briefing dates each presenter already has booked in the next N days.

    Availability only means something relative to a time, so when the caller
    gives no window we report forward load instead of a yes/no — "3 briefings
    booked in the next 30 days" is useful with or without a target date, where
    a bare available:true would not be.

    Note this covers BRIEFING commitments only. It knows nothing about their
    real calendar (meetings, travel, leave), which is why the wording is
    "booked" rather than "free".

    Returns {email: [YYYY-MM-DD, ...]} sorted ascending.
    """
    try:
        from opensearch_client import search
    except ImportError:
        return {}

    if not presenter_emails:
        return {}

    import time as _time

    now_ms = int(_time.time() * 1000)
    end_ms = now_ms + lookahead_days * 86400000

    body = {
        "query": {"bool": {"must": [
            {"range": {"startTime.utcMs": {"gte": now_ms, "lt": end_ms}}},
        ]}},
        "_source": [
            "startTime.utcMs",
            "startTime.requested.requestedZoneDate",
            PRESENTER_LIST,
        ],
        "size": _LOAD_SCAN_SIZE,
        "sort": [{START_TIME: {"order": "asc", "unmapped_type": "long"}}],
    }

    result = search(index=ACTIVITIES_INDEX, body=body, size_cap=_LOAD_SCAN_SIZE)
    if not result.get("success"):
        logger.warning(f"Upcoming-load lookup failed: {result.get('error')}")
        return {}

    email_set = {e.lower() for e in presenter_emails}
    load: Dict[str, List[str]] = {}

    for hit in result.get("hits", []):
        src = hit.get("source", {})
        local = _deep_get(src, "startTime.requested.requestedZoneDate") or ""
        day = local.split("T")[0] if "T" in local else local
        if not day:
            continue
        for pe in (src.get("activityData") or {}).get("topic_presenter") or []:
            # Declined slots are not commitments — reporting them as booked days
            # overstates how loaded someone is. Same rule as the conflict scan.
            if (pe.get("presenterStatus") or "").strip().lower() in _EXCLUDED_STATUSES:
                continue
            email = (
                _deep_get(pe, "presenter.primaryEmail") or pe.get("presenterEmail") or ""
            ).lower()
            if email in email_set:
                dates = load.setdefault(email, [])
                if day not in dates:
                    dates.append(day)

    logger.info(
        f"Upcoming load: {len(presenter_emails)} presenters over {lookahead_days}d, "
        f"{len(load)} with bookings"
    )
    return load


def _presenter_blocks_in_window(
    ranked: List[Dict[str, Any]],
    start_ms: int,
    end_ms: int,
    api_token: Optional[str],
    api_headers: Optional[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Blocked (non-briefing) time per presenter id, from the BriefingIQ API.

    Optional enrichment: without a token — background jobs, tests, any caller
    outside a request — this returns {} and availability falls back to briefing
    bookings alone, exactly as before. It never raises.

    One HTTP call per presenter, so it runs on the ranked pool rather than every
    candidate, and only when a time window was actually supplied.
    """
    if not api_token:
        return {}
    ids = [p.get("presenter_id") for p in ranked if p.get("presenter_id")]
    if not ids:
        return {}
    try:
        from tools.briefingiq_writer import get_presenter_blocks

        return get_presenter_blocks(
            ids, api_token, api_headers, start_ms=start_ms, end_ms=end_ms
        )
    except Exception as exc:
        # Availability is advisory; a calendar outage must not cost the caller
        # their presenter list.
        logger.warning(f"Presenter block lookup failed: {type(exc).__name__}: {exc}")
        return {}


def _event_revenue(event_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Opportunity revenue per event: initial, latest, and the delta between.

    The delta mirrors how the Oracle report computes it — measure against
    `closed` once a deal has finished, otherwise against the still-open value,
    always relative to `initial`. A missing initial is treated as 0, so a first
    figure with no baseline reads as its full value; `has_baseline` flags that
    so the caller can tell real growth from an absent starting point.

    EVENTS_VISIT_INFO is an array (one entry per opportunity), so entries are
    summed rather than taking [0] — otherwise a multi-opportunity event reports
    only its first deal.
    """
    try:
        from opensearch_client import search
    except ImportError:
        return {}

    ids = [e for e in event_ids if e]
    if not ids:
        return {}

    result = search(
        index=EVENTS_INDEX,
        body={
            "query": {"ids": {"values": ids[:200]}},
            "_source": [f"eventFormData.{EVT_OPP_SECTION}"],
            "size": 200,
        },
        size_cap=200,
    )
    if not result.get("success"):
        logger.warning(f"Event revenue lookup failed: {result.get('error')}")
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    for hit in result.get("hits", []):
        section = ((hit.get("source") or {}).get("eventFormData") or {}).get(EVT_OPP_SECTION)
        if section is None:
            continue
        if not isinstance(section, list):
            section = [section]

        initial = latest = 0.0
        saw_initial = saw_latest = False
        for opp in section:
            if not isinstance(opp, dict):
                continue
            i = opp.get(EVT_OPP_INITIAL)
            closed = opp.get(EVT_OPP_CLOSED)
            open_ = opp.get(EVT_OPP_OPEN)
            i = _coerce_amount(i)
            if i is not None:
                initial += i
                saw_initial = True
            # closed wins when present — a finished deal's final number is the
            # one to measure against, even when it is 0 (a lost deal).
            current = closed if closed is not None else open_
            current = _coerce_amount(current)
            if current is not None:
                latest += current
                saw_latest = True

        if not saw_latest and not saw_initial:
            continue
        out[hit.get("id")] = {
            "initial": initial if saw_initial else None,
            "latest": latest if saw_latest else None,
            "delta": (latest - initial) if saw_latest else None,
            "has_baseline": saw_initial,
        }

    logger.info(f"Revenue lookup: {len(ids)} events → {len(out)} with figures")
    return out


def get_suggested_presenters(
    topic: Optional[str] = None,
    industry: Optional[str] = None,
    customer_name: Optional[str] = None,
    event_id: Optional[str] = None,
    audience_level: Optional[str] = None,
    limit: int = 10,
    index: Optional[str] = None,
    check_start_utc_ms: Optional[int] = None,
    check_end_utc_ms: Optional[int] = None,
    api_token: Optional[str] = None,
    api_headers: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Query OpenSearch for presenters matching the given filters.

    Flow:
    1. If customer_name or industry, resolve them to a list of event_ids
       via the events index.
    2. Query the activities index filtered by those event_ids and/or topic.
    3. Aggregate presenters across matching activities, rank, return top N.

    Ranking order (see _rank_presenters): topic match tier → recency-weighted
    depth on that topic → accepted count → overall recency → event coverage.
    Revenue is attached as context and is deliberately not a ranking key.

    api_token / api_headers are the caller's BriefingIQ credentials, forwarded
    from the incoming request. When present AND a time window is given, the
    live presenter calendar is consulted for blocked time (leave, travel, holds)
    that the activities index cannot know about. Optional throughout: without
    them, availability is briefing bookings only, as before.

    audience_level is validated and echoed back, but has NO effect on ranking.
    The seniority tiebreak it used to drive is disabled — its two inputs are
    unusable on the current data, with the measurements recorded in
    _rank_presenters. Kept as a parameter so callers and the tool schema
    continue to work.
    """
    try:
        from opensearch_client import search
    except ImportError:
        return {
            "success": False,
            "error": "OpenSearch client not available",
            "suggested_presenters": [],
        }

    if audience_level and audience_level not in _AUDIENCE_LEVELS:
        return {
            "success": False,
            "error": f"Invalid audience_level '{audience_level}'. Expected one of: {sorted(_AUDIENCE_LEVELS)}",
            "suggested_presenters": [],
        }

    # Validate here rather than trusting the handler: this is a public function
    # and `limit` reaches it from an LLM tool call, so it is model-generated
    # input. A non-int or a huge value would otherwise reach the slicing and
    # the availability pool unchecked.
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return {
            "success": False,
            "error": f"limit must be an integer, got {limit!r}",
            "suggested_presenters": [],
        }
    limit = max(1, min(limit, _MAX_LIMIT))

    # A half-open window silently fell through to the no-window branch, which
    # reports forward load — so a caller who asked "is anyone free on the 3rd?"
    # got booking counts back and no answer to their actual question.
    if bool(check_start_utc_ms) != bool(check_end_utc_ms):
        return {
            "success": False,
            "error": "check_start_utc_ms and check_end_utc_ms must be given together",
            "suggested_presenters": [],
        }
    if check_start_utc_ms and check_end_utc_ms and check_start_utc_ms >= check_end_utc_ms:
        return {
            "success": False,
            "error": "check_start_utc_ms must be earlier than check_end_utc_ms",
            "suggested_presenters": [],
        }

    if not any([topic, industry, customer_name, event_id]):
        return {
            "success": False,
            "error": "At least one filter required: topic, industry, customer_name, or event_id",
            "suggested_presenters": [],
        }

    # Resolve event_ids from customer/industry scope (if not already given)
    scoped_event_ids: List[str] = []
    dropped_scope: Optional[str] = None
    if event_id:
        scoped_event_ids = [event_id]
    elif customer_name or industry:
        scoped_event_ids = _fetch_event_ids_by_scope(customer_name, industry)
        if not scoped_event_ids:
            # A customer with no history here is the normal case for a first
            # briefing — the very moment presenter suggestions are most useful.
            # Returning nothing would discard a perfectly good topic, so fall
            # through to topic-only matching and tell the caller we did.
            if topic:
                dropped_scope = customer_name or industry
                logger.info(
                    f"No events for scope {dropped_scope!r}; falling back to topic-only "
                    f"search on {topic!r}"
                )
            else:
                return {
                    "success": True,
                    "suggested_presenters": [],
                    "message": "No matching events found for customer/industry scope",
                }

    # Need at least one constraint on activities (event_ids OR topic)
    if not scoped_event_ids and not topic:
        return {
            "success": True,
            "suggested_presenters": [],
            "message": "No activity constraint could be derived",
        }

    target_index = index or ACTIVITIES_INDEX
    logger.info(
        f"Presenter search: topic={topic}, industry={industry}, "
        f"customer={customer_name}, event_id={event_id}, scoped_events={len(scoped_event_ids)}"
    )

    def _run(topic_filter: Optional[str]) -> Dict[str, Any]:
        body = {
            "query": _build_activity_query(
                topic=topic_filter,
                event_ids=scoped_event_ids or None,
            ),
            "size": 500,
            "sort": [{START_TIME: {"order": "desc", "unmapped_type": "long"}}],
        }
        # Explicit cap — search() otherwise clamps to _MAX_SIZE (50), which
        # silently truncates the pool the ranking sees.
        return search(index=target_index, body=body, size_cap=500)

    result = _run(topic)

    if not result.get("success"):
        return {
            "success": False,
            "error": result.get("error", "Search failed"),
            "suggested_presenters": [],
        }

    hits = result.get("hits", [])
    topic_query = topic
    logger.info(f"Presenter search returned {len(hits)} activity hits")

    # No activity satisfies every word of the topic. Rather than loosening to
    # any-word (which always returns somebody, for any string), report the miss.
    if topic and not hits:
        if scoped_event_ids:
            # An event/customer scope was asked for, so the caller still wants
            # that event's presenters — drop the topic filter but say so.
            logger.info(f"No strict topic match for {topic!r}; retrying scope-only")
            result = _run(None)
            hits = result.get("hits", []) if result.get("success") else []
            topic_query = None
        else:
            empty: Dict[str, Any] = {
                "success": True,
                "suggested_presenters": [],
                "searched_topic": topic,
                "closest_topics": _closest_topics(target_index, topic),
                "available_topics": _available_topics(target_index),
                "message": (
                    f"No one has presented on '{topic}'. No activity topic contains "
                    "every word of it."
                ),
                "guidance": (
                    "closest_topics share at least one word with what was asked; "
                    "available_topics is the full vocabulary. Pick the closest "
                    "genuinely related one, re-query with it, and tell the user "
                    "plainly which topic you substituted and why — or report that "
                    f"nobody has presented on '{topic}'. Saying nobody matches is a "
                    "valid, useful answer. Never describe these presenters as having "
                    f"'{topic}' experience."
                ),
            }
            logger.info(
                f"No strict match for topic={topic!r}; returned "
                f"{len(empty['closest_topics'])} closest / "
                f"{len(empty['available_topics'])} available topics"
            )
            return empty

    unrelated_fallback = False
    if not hits and (customer_name or industry or event_id):
        logger.info("Scoped search returned 0 — falling back to top presenters overall")
        fallback_body = {
            "query": {"exists": {"field": PRESENTER_EMAIL_FIELD}},
            "size": 200,
            "sort": [{START_TIME: {"order": "desc", "unmapped_type": "long"}}],
        }
        fb_result = search(index=target_index, body=fallback_body, size_cap=200)
        if fb_result.get("success"):
            hits = fb_result.get("hits", [])
            unrelated_fallback = bool(hits)
            topic_query = None
            logger.info(f"Fallback search returned {len(hits)} activity hits")

    if not hits:
        return {
            "success": True,
            "suggested_presenters": [],
            "message": "No matching activities with presenters found",
        }

    presenters = _extract_presenters_from_hits(hits, topic_query=topic_query)

    # Rank a wider pool when availability is going to reorder the list. The
    # availability pass can only promote people it can see, so cutting to
    # `limit` first means a free presenter ranked just below the cut is never
    # reachable — ask for 10 on a day all 10 are booked and the free 11th stays
    # invisible. Widening costs nothing at the index: _check_presenter_conflicts
    # queries by time window and filters emails locally, so 30 candidates is the
    # same single request as 10.
    window_given = bool(check_start_utc_ms and check_end_utc_ms)
    pool_limit = limit * _AVAILABILITY_POOL_FACTOR if window_given else limit
    ranked = _rank_presenters(presenters, pool_limit, audience_level=audience_level)

    logger.info(
        f"Found {len(ranked)} unique presenters from {len(hits)} activities"
        + (f" (pool of {pool_limit} for availability)" if window_given else "")
        + (f" (audience_level={audience_level})" if audience_level else "")
    )

    # Calendar lookups must cover EVERY address a person holds — deduping on
    # uniqueId means `email` is only whichever came first, and bookings filed
    # under their other address would otherwise be invisible.
    all_emails = sorted({e for p in ranked for e in p.get("all_emails") or []})

    if check_start_utc_ms and check_end_utc_ms:
        # A window was given: answer the yes/no question directly.
        conflicts = _check_presenter_conflicts(
            all_emails,
            check_start_utc_ms,
            check_end_utc_ms,
            exclude_event_id=event_id,
        )
        # The index only records briefing bookings, so leave, travel and manual
        # holds are invisible to it. Ask BriefingIQ for those before deciding
        # who is free — a presenter with nothing booked may still be on leave.
        blocks = _presenter_blocks_in_window(
            ranked, check_start_utc_ms, check_end_utc_ms, api_token, api_headers
        )
        for p in ranked:
            hits_for_p = [c for e in (p.get("all_emails") or []) for c in conflicts.get(e, [])]
            blocked = blocks.get(p.get("presenter_id") or "", [])
            p["available"] = not hits_for_p and not blocked
            p["conflicts"] = hits_for_p[:3]  # cap at 3 for LLM context
            if blocked:
                p["blocked_time"] = blocked[:3]
                p["blocked_note"] = (
                    f"{len(blocked)} calendar block(s) in this window "
                    f"({', '.join(sorted({b['kind'] for b in blocked}))}) — "
                    "not a briefing, so this is time they are otherwise unavailable"
                )
        # Demote the double-booked rather than dropping them — a clashing
        # presenter may still get freed up, so they stay in the list, just not
        # at the top. sort() is stable, so ranking order survives inside each
        # group. Only now is the pool cut to what the caller asked for, so a
        # free presenter from deeper in the ranking can take a booked one's slot.
        ranked.sort(key=lambda p: 0 if p.get("available") else 1)
        ranked = ranked[:limit]
    elif all_emails:
        # No window given. "Available" is meaningless without a time, so report
        # forward load instead — useful whether or not a date is in play, and
        # honest about being briefing bookings rather than a real calendar.
        load = _upcoming_load(all_emails, lookahead_days=_LOOKAHEAD_DAYS)
        for p in ranked:
            dates = sorted({d for e in (p.get("all_emails") or []) for d in load.get(e, [])})
            p["upcoming_bookings"] = len(dates)
            p["upcoming_dates"] = dates[:5]
            p["availability_note"] = (
                f"{len(dates)} briefing day(s) booked in the next {_LOOKAHEAD_DAYS} days"
                if dates
                else f"no briefings booked in the next {_LOOKAHEAD_DAYS} days"
            )

    # Revenue at the briefings each presenter appeared at. Context only — it is
    # deliberately absent from the sort key, because the figure belongs to the
    # briefing rather than to any one of its several presenters.
    revenue = _event_revenue(sorted({e for p in ranked for e in p.get("event_ids") or []}))
    if revenue:
        for p in ranked:
            mine = [revenue[e] for e in (p.get("event_ids") or []) if e in revenue]
            deltas = [m["delta"] for m in mine if m.get("delta") is not None]
            if not deltas:
                continue
            total = sum(deltas)
            no_baseline = sum(1 for m in mine if not m.get("has_baseline"))
            p["revenue_events"] = len(deltas)
            p["revenue_delta"] = round(total, 2)
            p["revenue_note"] = (
                f"opportunities at their {len(deltas)} briefing(s) moved "
                f"{'+' if total >= 0 else ''}{total:,.0f} in total — shared across all "
                "presenters at those briefings, not attributable to this person alone"
                + (f"; {no_baseline} had no starting figure" if no_baseline else "")
            )

    payload: Dict[str, Any] = {
        "success": True,
        "suggested_presenters": ranked,
        "total_activities_matched": result.get("total_hits", len(hits)),
        "audience_level": audience_level,
    }
    if topic:
        payload["searched_topic"] = topic
    if dropped_scope:
        payload["scope_dropped"] = dropped_scope
        payload["note"] = (
            f"No past events found for '{dropped_scope}', so these are matched on topic "
            f"'{topic}' alone, not on any history with that customer. Say so when "
            "presenting them."
        )
    if topic and topic_query is None:
        # The topic filter was dropped to salvage a scoped request. These people
        # are the event's presenters, not matches for what was asked.
        payload["topic_filter_dropped"] = topic
        payload["note"] = (
            f"No activity topic contains every word of '{topic}', so these presenters "
            "come from the requested event/customer scope only — they are NOT matched "
            f"on '{topic}'. Do not describe them as having presented it."
        )
    if unrelated_fallback:
        payload["unrelated_fallback"] = True
        payload["note"] = (
            "Nothing matched the requested scope, so these are simply the most recent "
            "presenters overall — unrelated to what was asked. Say so, or ask the user "
            "to broaden the request."
        )
    return payload
