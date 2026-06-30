"""Compile an AccessContext into OpenSearch filter clauses (Phase 2).

This turns the role + scope resolved by access/resolver.py into a list of
OpenSearch `bool.filter` clauses. It does NOT enforce anything yet — callers log
the compiled filter so we can eyeball it against real users before Phase 3 wires
it into opensearch_client.search().

Where the rules come from (see docs/RBAC_ACCESS_MODEL_GUIDE.md):
  - BI_ROLE_REQUEST_ACCESS_MAP      — row rules for global roles
  - M_EVENT_ROLE_DATA_ACCESS_MAP    — row rules for the 6 event roles (Requester, …)
Both share the shape (PROPERTY_NAME, OPERATION, PROPERTY_VALUE), so we normalise
them into one Rule type and translate each to an OpenSearch clause.

Combination policy (decided with the user):
  - within a role:  combine by the rule's FIELD_CONDITION (and/or), default AND
  - across a user's roles:  OR  (most-permissive — any role that grants access wins)
  - unknown / ruleless role:  fall back to the most-restrictive known shape
                              (own/hosted requests only)
"""

import os
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from sqlalchemy import text

from database import engine
from logging_config import get_logger

logger = get_logger(__name__)

# --- field translation: Oracle property name -> OpenSearch keyword field --------
_FIELD_MAP = {
    "hostEmail": "eventFormData.VISIT_INFO.oracleHostEmail.keyword",
    "state": "status.stateCode.keyword",
    "status.uniqueId": "status.uniqueId.keyword",
}

# `createdBy` has no top-level event field in OpenSearch (Phase 0 finding), so
# "owned by me" is expressed as host OR requester == me.
_OWNERSHIP_FIELDS = [
    "eventFormData.VISIT_INFO.oracleHostEmail.keyword",
    "eventFormData.VISIT_INFO.requesterEmail.keyword",
]

_LOCATION_FIELD = "location.uniqueId.keyword"

# Most-restrictive known shape, used as the fail-safe fallback for unknown roles.
def _ownership_clause(email: str) -> dict:
    return {"bool": {"should": [{"term": {f: email}} for f in _OWNERSHIP_FIELDS]}}


@dataclass
class Rule:
    property: str
    operation: str  # eq | in | notin
    value: str
    condition: str = "and"  # how this role's rules combine: and | or


# --- rule loading (cached, both tables) -----------------------------------------
_CACHE_TTL_SECONDS = 300
_rules_cache: dict = {}
_cache_lock = threading.Lock()


def _load_role_rules(role_ids: List[int]) -> Dict[int, List[Rule]]:
    """Load row rules for the given roles. Cached per role set.

    Source: M_EVENT_ROLE_DATA_ACCESS_MAP — the complete, current row-rule table
    (covers all 12 roles incl. the common event roles, and carries the status
    filters). BI_ROLE_REQUEST_ACCESS_MAP encodes an older/global grant model with
    conflicting combine semantics; reconciling the two is a Phase-3 decision.
    """
    if not role_ids:
        return {}
    key = tuple(sorted(role_ids))
    now = time.time()
    with _cache_lock:
        hit = _rules_cache.get(key)
        if hit and now - hit[0] < _CACHE_TTL_SECONDS:
            return hit[1]

    out: Dict[int, List[Rule]] = {rid: [] for rid in role_ids}
    binds = {f"r{i}": rid for i, rid in enumerate(role_ids)}
    in_clause = ",".join(f":r{i}" for i in range(len(role_ids)))
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"SELECT role_id, property_name, operation, property_value, "
                f"  NVL(field_condition, 'and') "
                f"FROM M_EVENT_ROLE_DATA_ACCESS_MAP "
                f"WHERE role_id IN ({in_clause}) AND TRIM(is_active) = '1' "
                f"  AND resource_name = 'REQUEST' AND property_name IS NOT NULL"
            ),
            binds,
        ).fetchall()
        for rid, prop, op, val, cond in rows:
            out.setdefault(int(rid), []).append(
                Rule(property=prop, operation=(op or "").lower(),
                     value=val, condition=(cond or "and").lower())
            )

    with _cache_lock:
        _rules_cache[key] = (now, out)
    return out


# --- translation: one Rule -> one OpenSearch clause -----------------------------
def _clause_for_rule(rule: Rule, email: Optional[str]) -> Optional[dict]:
    val = (rule.value or "").strip()
    # ownership: createdBy/hostEmail compared to the logged-in user
    if val == "$loggedInUser":
        if not email:
            return None
        if rule.property == "createdBy":
            return _ownership_clause(email)
        field = _FIELD_MAP.get(rule.property)
        return {"term": {field: email}} if field else None

    field = _FIELD_MAP.get(rule.property)
    if not field:
        logger.debug(f"[rbac] no field mapping for property '{rule.property}'")
        return None

    values = [v.strip() for v in val.split(",") if v.strip()]
    if rule.operation == "eq":
        return {"term": {field: values[0]}} if values else None
    if rule.operation == "in":
        return {"terms": {field: values}}
    if rule.operation == "notin":
        return {"bool": {"must_not": {"terms": {field: values}}}}
    logger.debug(f"[rbac] unknown operation '{rule.operation}'")
    return None


def _compile_role(rules: List[Rule], email: Optional[str]) -> Optional[dict]:
    """Combine one role's rules into a single bool clause (by their condition)."""
    clauses = [c for c in (_clause_for_rule(r, email) for r in rules) if c]
    if not clauses:
        return None
    # default AND; if any rule says 'or', the role's rules are unioned
    use_or = any(r.condition == "or" for r in rules)
    return {"bool": {("should" if use_or else "must"): clauses}}


def compile_access_filter(ctx) -> List[dict]:
    """AccessContext -> list of OpenSearch bool.filter clauses (AND-ed together).

    Returns [] only when there is genuinely no restriction to apply. For an
    unresolved/ruleless context we return the most-restrictive ownership filter
    (fail-safe), not an empty list.
    """
    filters: List[dict] = []

    # 1. Location scope (the LOCATION_SENSITIVE dimension) — always AND-ed.
    if getattr(ctx, "location_guids", None):
        filters.append({"terms": {_LOCATION_FIELD: ctx.location_guids}})

    # 2. Row rules per role, OR-ed across the user's roles (most-permissive).
    role_ids = getattr(ctx, "role_ids", None) or []
    email = getattr(ctx, "email", None)
    role_rules = _load_role_rules(role_ids)
    per_role = [c for c in (_compile_role(rs, email) for rs in role_rules.values()) if c]

    if per_role:
        filters.append({"bool": {"should": per_role}} if len(per_role) > 1 else per_role[0])
    elif not getattr(ctx, "resolved", False):
        # Fail-safe: unknown/unresolved → most-restrictive known shape (own/hosted only).
        if email:
            filters.append(_ownership_clause(email))
        else:
            filters.append({"bool": {"must_not": {"match_all": {}}}})  # deny-all

    return filters


# --- enforcement helpers (Phase 3) ---------------------------------------------
# A clause that references an ownership or location field constrains *which events*
# a user can see (so activities must be scoped too). A clause that only touches
# status does not narrow the set of events by identity — every user with that role
# sees the same events. We use this to spot "see-everything" users cheaply.
def _clause_is_event_narrowing(clause: dict) -> bool:
    """True if a clause restricts the set of events by who/where (not just status)."""
    import json
    blob = json.dumps(clause)
    if _LOCATION_FIELD in blob:
        return True
    return any(f in blob for f in _OWNERSHIP_FIELDS)


def is_unrestricted(ctx) -> bool:
    """True if the user can see every event in scope (no identity/location narrowing).

    Roles combine with OR, so a single non-narrowing role (e.g. Super User, whose
    only rule is a status filter) means the user effectively sees all events —
    regardless of ownership clauses contributed by their other roles. Such users
    need no activities lookup. (A status-only filter still applies on the events
    index; for activities we treat these users as unrestricted — an accepted
    approximation for high-privilege roles.)
    """
    if not getattr(ctx, "resolved", False):
        return False
    if getattr(ctx, "location_guids", None):
        return False  # location AND-limits events, so not fully unrestricted
    role_rules = _load_role_rules(getattr(ctx, "role_ids", None) or [])
    email = getattr(ctx, "email", None)
    for rules in role_rules.values():
        clause = _compile_role(rules, email)
        # a role with no rules, or one that only filters by status, is non-narrowing
        if clause is None or not _clause_is_event_narrowing(clause):
            return True
    return False


# Join key between events and activities (Case 3). `activities.eventId` references
# the parent event; EVENT_JOIN_FIELD is the events-index _source field whose value
# equals that reference. In production these must align — VERIFY in the target
# environment (in some snapshots events use a CBR code while activities use a GUID,
# in which case this must point at the events-side GUID field).
EVENT_JOIN_FIELD = os.getenv("RBAC_EVENT_JOIN_FIELD", "eventId")
ACTIVITY_EVENT_FIELD = os.getenv("RBAC_ACTIVITY_EVENT_FIELD", "eventId.keyword")


def allowed_event_ids(ctx, search_fn, cap: int = 1024):
    """Case 3: the event ids this user may see, for scoping activities.

    Runs the event-access filter against the events index asking only for the join
    field. Returns (ids, overflow): overflow=True when the count exceeds `cap`,
    signalling the caller to fail closed rather than ship a giant terms query.
    """
    filt = compile_access_filter(ctx)
    body = {
        "size": cap + 1,
        "_source": [EVENT_JOIN_FIELD],
        "query": {"bool": {"filter": filt, "must": [{"match_all": {}}]}},
    }
    resp = search_fn("events", body)
    hits = resp.get("hits", []) if isinstance(resp, dict) else []
    ids = [h.get("source", {}).get(EVENT_JOIN_FIELD) for h in hits]
    ids = [i for i in ids if i]
    if len(ids) > cap:
        return [], True
    return ids, False
