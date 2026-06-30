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
  [2] BUILD FILTER                         ← ⬜ TODO (Phase 2)
     role  →  its rules  →  list of OpenSearch conditions
     (e.g. location in [my locations], my own requests, etc.)
     │
     ▼
  [3] LLM WRITES SEARCH  (untrusted — only knows WHAT you asked)
     │
     ▼
  [4] INJECT FILTER AT CHOKEPOINT          ← ⬜ TODO (Phase 3)
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

## ⚠️ Open items / Phase 4

- **🚨 Normalizer bug (BLOCKER):** `normalize_query_structure()` in
  `opensearch_client.py` strips the `bool` wrapper from items inside a `filter`
  array — turning `filter:[{bool:{must_not:…}}]` into the invalid
  `filter:[{must_not:…}]`, which silently matches nothing. Our compiled filters
  use nested `bool`/`must_not`/`should`, so Phase 3 must either fix that
  normalizer or inject in a structure that survives it.
- **Fail-closed:** today a resolution failure is fail-*open* (query runs unfiltered).
  When enforcement lands, a failure must **deny / return nothing** instead.
- **`createdBy` gap:** events have no top-level `createdBy` in OpenSearch; using
  `oracleHostEmail` / `requesterEmail` as the ownership proxy (implemented).
- **Two rule tables:** Phase 2 uses `M_EVENT_ROLE_DATA_ACCESS_MAP` only.
  `BI_ROLE_REQUEST_ACCESS_MAP` (older/global, conflicting combine semantics) is
  ignored for now — reconcile in Phase 3 if needed.
