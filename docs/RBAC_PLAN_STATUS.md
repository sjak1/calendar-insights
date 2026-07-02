# RBAC — Plan & Status

A one-look view of the architecture and how far we've gotten.
(Deep details live in [RBAC_ACCESS_MODEL_GUIDE.md](RBAC_ACCESS_MODEL_GUIDE.md).)

---

## The architecture (simple flow)

```
  REQUEST  (headers: email + categoryid + customerid)
     │
     ▼
  [1] RESOLVE ROLE                         ← ✅ DONE (Phase 1)
     email + category  →  Oracle lookup  →  role(s) + allowed locations
     (access/resolver.py)
     │
     ▼
  [2] BUILD FILTER                         ← ✅ DONE (Phase 2)
     role  →  its rules  →  list of OpenSearch conditions
     (e.g. location in [my locations], my own requests, etc.)
     │
     ▼
  [3] LLM WRITES SEARCH  (untrusted — only knows WHAT you asked)
     │
     ▼
  [4] INJECT FILTER AT CHOKEPOINT          ← ✅ DONE (Phase 3, events)
     search() wraps:  { filter: [my filter], must: [LLM query] }
     (opensearch_client.py)
     │
     ▼
  OPENSEARCH  →  only data I'm allowed to see
```

**One-liner:** the LLM decides *what* you search; the server decides *what you may
see* and staples it on right before the DB, where the LLM can't touch it.

---

## Progress

| Phase | What | Status |
|-------|------|--------|
| **0** | Verify scoping fields exist in OpenSearch | ✅ done |
| **1** | Resolve caller's role + scope from Oracle (resolve + log only) | ✅ done |
| **2** | Compile role → OpenSearch filter clauses | ✅ done |
| **3** | Inject filter at `search()` chokepoint (real enforcement) | ✅ events done · ⚠️ activities join unverified |
| **4** | Tests + fail-closed guard + (optional) pre-check | ⬜ todo |

---

## What's built so far (Phase 1)

- `access/resolver.py` — `resolve_access_context(email, category, customer)` →
  `AccessContext` (role names, role ids, allowed location GUIDs). Cached, fail-soft.
- `access/__init__.py` — exports the above.
- `query_processor.py` (`handle_query`) — calls it and **logs** the result
  (`🔐 [rbac] ...`). No enforcement yet.

**Verified working:** real users resolve their roles; unknown/missing email →
`resolved=False`.

## What's built so far (Phase 2)

- `access/policy.py` — `compile_access_filter(ctx)` → list of OpenSearch
  `bool.filter` clauses. Rules loaded (cached) from `M_EVENT_ROLE_DATA_ACCESS_MAP`.
  Multi-role = OR (most-permissive); unknown/unresolved = own/hosted-only fallback.
- Wired into `handle_query` — logs the compiled filter next to the context.

**Verified live (via raw OpenSearch client):**
- Super User → 6 of 10 docs (all non-draft). ✅
- Unknown user → 0 docs (own-only fallback, fail-safe). ✅

**Translation notes:**
- `createdBy = $loggedInUser` → `oracleHostEmail = me OR requesterEmail = me`
  (no top-level `createdBy` in OpenSearch — Phase 0 gap).
- `status.uniqueId notin (drafts)` → `must_not terms` on `status.uniqueId.keyword`.
- location scope → `terms` on `location.uniqueId.keyword` (from Phase-1 GUIDs).

---

## Key facts driving the design

- Roles are **per (user, category)** — not global. Category comes in the header.
- Access rules are **already stored in the briefing app's Oracle tables** — we read
  + translate them, we don't invent them.
- Oracle uses **numeric ids**, OpenSearch uses **GUIDs** — bridged via
  `M_LOCATION` / `M_CATEGORY`.
- Enforcement lives in **one place** (`search()`), never in the LLM.

---

## What's built so far (Phase 3 — enforcement)

- `access/context.py` — request-scoped contextvar; `set_access(ctx, event_id)` in
  `handle_query`, read at the `search()`/`count()` chokepoint. Unset (scripts/tests)
  → no enforcement (legacy behavior preserved).
- `opensearch_client._apply_access()` — injects the filter **after**
  `normalize_query_structure` (sidesteps the normalizer bug):
  - **events** → wrap `{bool: {must:[LLM query], filter:[access clauses]}}`.
  - **activities** → 3 cases: (1) unrestricted role → no filter; (2) pinned eventId
    (header) → check that one event, scope to it or deny; (3) broad → scope to
    `allowed_event_ids` (capped at 1024 → deny on overflow).
  - other/wildcard index → deny if unresolved, else pass-through (v1).
- `access/policy.py` — added `is_unrestricted(ctx)` (per-role, OR-aware) and
  `allowed_event_ids(ctx, search_fn, cap)`.

**Verified live (enforced via search()):**
| user | events | activities |
|------|--------|------------|
| no context (legacy) | 146 | 3975 |
| Super User | 59 (non-draft) | 3975 (unrestricted) |
| Requester (own only) | 34 | 0 (fail-closed) |
| unknown | 0 (deny) | 0 (deny) |

**🚧 Activities join is UNVERIFIED in this environment.** In the test data,
`activities.eventId` is a GUID while `events.eventId` is a CBR code with no matching
GUID — the two indices are non-joinable snapshots, so Case 3 yields 0 (fails closed,
safe). The join field is now configurable via `RBAC_EVENT_JOIN_FIELD` /
`RBAC_ACTIVITY_EVENT_FIELD`; **must be confirmed against real prod data** before
activities scoping can be trusted as correct (vs merely safe).

## Resolved during Phase 3

- **Normalizer bug — sidestepped.** `_apply_access()` injects the filter *after*
  `normalize_query_structure()` runs, so our nested `bool`/`must_not`/`should` is
  never mangled. (The normalizer is still buggy for LLM-written nested bool-in-filter,
  but that's a separate pre-existing issue.)
- **Fail-closed — done.** On resolution error, `handle_query` sets an unresolved
  context so the chokepoint denies rather than running unfiltered.
- **`logger` NameError — fixed.** `opensearch_client.py` now defines a logger.
- **count() leak — fixed.** No-index count/search now defaults to the events filter
  instead of passing through unfiltered.
- **`createdBy` gap — handled.** Proxied as `oracleHostEmail OR requesterEmail`.

---

## The dimensions of access control (full picture)

RBAC can act at shrinking levels of zoom. We built the outermost only.

| Dimension | Controls | Mechanism | Source table | Status |
|-----------|----------|-----------|--------------|--------|
| **Row access** | which events | WHERE filter | `M_EVENT_ROLE_DATA_ACCESS_MAP` | ✅ built |
| **Private records** | creator-only records | WHERE filter | `BI_ROLE_DATA_ACCESS_MAP.PRIVATE_ACCESS` + event `isPrivate` | ❌ |
| **Location scoping** | your sites only | WHERE filter | `BI_LOCATION_USER`→`M_LOCATION` (GUIDs resolved) | ⚠️ partial |
| **Entity access** | notes / audit / attendees | strip from result | `BI_ROLE_DATA_ACCESS_MAP.READ_ACCESS` per resource | ❌ |
| **Field redaction** | hide revenue etc. | strip from result | `BI_ROLE_DATA_ACCESS_MAP` (field config) | ❌ |
| **CRUD / write** | create/edit/delete | permission check | `BI_ROLE_DATA_ACCESS_MAP.CREATE/UPDATE` | ➖ read-only |

**Key insight:** row/private/location are all the same **WHERE-filter** mechanism (easy,
extend `_apply_access`). Entity + field redaction are a **new "strip from results"**
mechanism (post-`search()`). CRUD only matters for the one agenda-push write path.

---

## Remaining TODOs (roadmap)

| # | Task | Source table / field | Where to apply | Mechanism | Phase | Effort |
|---|------|----------------------|----------------|-----------|-------|--------|
| 1 | Verify activities join | `activities.eventId` vs events | `opensearch_client` activities path | confirm key in prod, set `RBAC_EVENT_JOIN_FIELD` | 3 finish | S |
| 2 | Finish location scoping | `BI_LOCATION_USER`→`M_LOCATION` | `_apply_access` (events) | add `terms: location.uniqueId ∈ my GUIDs` | 4 | S |
| 3 | Private records | `BI_ROLE_DATA_ACCESS_MAP.PRIVATE_ACCESS` + `isPrivate` | `_apply_access` (events) | WHERE: `isPrivate=false OR creator=me` | 4 | S |
| 4 | Fail-closed hardening | — | `_apply_access` (other/wildcard idx) | deny unknown indices | 4 | S |
| 5 | Automated test suite | — | `tests/` | pytest matrix per role | 4 | M |
| 6 | Entity access (notes/audit) | `BI_ROLE_DATA_ACCESS_MAP.READ_ACCESS` | after `search()` | strip sub-objects | 5 | M |
| 7 | Field redaction (revenue) | `BI_ROLE_DATA_ACCESS_MAP` (fields) | after `search()` | `_source` strip | 5 | M |
| 8 | Agenda-push write gate | `BI_ROLE_DATA_ACCESS_MAP.CREATE/UPDATE` | `tools/handlers.py` push_agenda | one "can write?" check | 6 | S |
| 9 | Reconcile 2nd rule table | `BI_ROLE_REQUEST_ACCESS_MAP` | `access/policy.py` loader | decide merge vs ignore | 4 | S |
| 10 | Pre-check (nice UX) | — | `api.py` before LLM | "you don't have access to X" msg | opt | S |

### Phasing
```
Phase 3 (finish):  #1 activities join verify
Phase 4 (row-level polish):  #2 location · #3 private · #4 fail-closed · #5 tests · #9 reconcile
Phase 5 (redaction — new mechanism):  #6 entity access · #7 field redaction
Phase 6 (writes):  #8 agenda-push gate
Optional:  #10 pre-check
```

### Suggested next-session pickup order
1. **#3 Private records** — cheap, real gap, same filter style
2. **#2 Location scoping** — already half-resolved
3. **#5 Tests** — lock in what works before adding more
4. **#6/#7 Redaction** — when roles should differ on *content*, not just which events
