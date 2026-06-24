# Role-Based Access in Calendar Insights — A Reading Guide

> A guide to understand (a) what we're trying to solve, and (b) the access-control
> data that already exists in the briefing app's Oracle DB, so you can explore the
> tables yourself with context.
>
> *Source: live inspection of schema `BIQ_EIQ_AURORA` (the schema this service connects to).*

---

## 1. The Problem (brief)

Today, **this service has no data-access control.**

- The user's identity arrives in headers (`x-cloud-user` = email, `x-cloud-customerid`, etc.)
but is only **logged** — never used to restrict data. See `api.py` (~line 139–168).
- The **LLM writes a raw OpenSearch query**, and `opensearch_client.py → search()` runs it
**as-is**. Nothing scopes it to a tenant, a location, or a person.
- Result: **everyone effectively sees everything.** A sales rep, an admin, a presenter —
same data. The briefing app *does* enforce roles; this service doesn't.

**Goal:** make this service respect the same role-based access the briefing app already
enforces — so a user sees here only what they're allowed to see there.

**Core principle:** access control is **never** enforced by the LLM (it can be tricked or
hallucinate). It's enforced by *our server code*, which wraps whatever the LLM produced in a
mandatory filter the model can't remove. One chokepoint: `search()`.

---

## 2. The Big Realisation

We assumed we'd have to *invent* a role→permission map. We don't.
**The briefing app already stores the entire access model in Oracle.** Our job is to
**read it and translate it** from SQL-shape into OpenSearch-shape — not to design it.

The model has **two layers**, both keyed by `(ROLE_ID, TENANT_ID)`:


| Layer                       | Table                          | What it controls                                                                                               | Granularity       |
| --------------------------- | ------------------------------ | -------------------------------------------------------------------------------------------------------------- | ----------------- |
| **1. Resource permissions** | `BI_ROLE_DATA_ACCESS_MAP`      | For each role × resource-type: can you Read/Create/Update/Delete? Plus `private` & `location-sensitive` flags. | Entity-type level |
| **2. Row restrictions**     | `BI_ROLE_DATA_SQL_RESTRICTION` | A literal SQL `WHERE` clause per role × resource, with a `$loggedInUser` placeholder.                          | Row level         |


---

## 3. The Tables That Matter

There are ~19 role-related tables in the schema. The ones relevant to **data access**:

### `BI_ROLE` — the role catalog

Defines the roles. Key columns:


| Column          | Meaning                                |
| --------------- | -------------------------------------- |
| `ID`            | role id (used everywhere as `ROLE_ID`) |
| `NAME`          | human name ("Briefing Manager", …)     |
| `TENANT_ID`     | which tenant this role belongs to      |
| `IS_EVENT_ROLE` | event-scoped role vs. global role      |
| `PARENT_ID`     | role hierarchy                         |
| `IS_ACTIVE`     | active flag                            |


### `BI_ROLE_DATA_ACCESS_MAP` — resource CRUD permissions (130 rows)

The heart of Layer 1. One row per `(role, resource)`:


| Column                                                              | Meaning                                        |
| ------------------------------------------------------------------- | ---------------------------------------------- |
| `ROLE_ID`, `TENANT_ID`                                              | who this applies to                            |
| `RESOURCE_NAME`                                                     | the entity type (see §5)                       |
| `READ_ACCESS` / `CREATE_ACCESS` / `UPDATE_ACCESS` / `DELETE_ACCESS` | 1/0 CRUD flags                                 |
| `PRIVATE_ACCESS`                                                    | 1 = private rows visible only to their creator |
| `LOCATION_SENSITIVE`                                                | 1 = rows scoped to the user's location(s)      |
| `IS_ACTIVE`                                                         | active flag                                    |


### `BI_ROLE_DATA_SQL_RESTRICTION` — row-level WHERE filters (4 rows)

Layer 2. The actual filter expressions:


| Column          | Meaning                                                    |
| --------------- | ---------------------------------------------------------- |
| `ROLE_ID`       | which role                                                 |
| `RESOURCE_NAME` | which entity                                               |
| `OPERATION`     | how clauses combine (`or` / `and`)                         |
| `SQL_QUERY`     | the literal WHERE clause, with `$loggedInUser` placeholder |
| `LOCATION_ID`   | optional location scoping                                  |


### Supporting tables (explore later)


| Table                                                                      | Purpose                                                                |
| -------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| `M_USER_ROLE` / `APP_USERS_AND_ROLES`                                      | maps a **user → role(s)**                                              |
| `locationuser` (resource)                                                  | maps a **user → location(s)** — needed to resolve `LOCATION_SENSITIVE` |
| `BI_ROLE_REQUEST_ACCESS_MAP`                                               | role access to specific request/event states                           |
| `M_ROLE_MODULE_ACCESS`, `M_ROLE_FEATURE_ACCESS`, `M_ROLE_DASHBOARD_ACCESS` | UI/feature gating (not data)                                           |
| `MAP_BIQ_TO_EIQ_ROLE`                                                      | maps legacy (BIQ) roles → new (EIQ) roles                              |


---

## 4. The Roles (12 total)

From `BI_ROLE`:


| ID  | Role                |
| --- | ------------------- |
| 1   | Super User          |
| 2   | Briefing Manager    |
| 3   | Scheduler           |
| 4   | Application User    |
| 5   | Technical Manager   |
| 6   | CRM_USER            |
| 8   | Event Manager       |
| 9   | Presenter           |
| 10  | Requester           |
| 11  | Super Admin         |
| 12  | Executive Scheduler |
| 13  | Support User        |


⚠️ **Only 5 of these have rows in `BI_ROLE_DATA_ACCESS_MAP` in this tenant:**
Application User, Briefing Manager, Scheduler, Super User, Technical Manager.
The other 7 (Super Admin, Event Manager, Presenter, Requester, CRM_USER, Executive
Scheduler, Support User) have **no data-access rows here** — they may default elsewhere,
inherit via `PARENT_ID`, or simply not be provisioned in this tenant. **Confirm before
relying on this.**

---

## 5. The Resources (26 entity types)

`RESOURCE_NAME` values in `BI_ROLE_DATA_ACCESS_MAP` — these are the *things* access is
granted on:

```
request                 requestactivity         requestactivityday
requestpresenter        requestTechnicalDetail  requestTypeActivity
requesttype             presenter               topic
topictype               attendees               note
location                locationcalendar        locationparameter
locationuser            assetmaster             assetdetail
templatemaster          templatedetail          lookupvalue
notification            audit                   user
vendor                  tenantaccount
```

These map to the briefing/event data — and roughly to the objects we query in OpenSearch
(`request` ≈ event, `presenter`, `attendees`, `topic`, `note`, `location`, …).

---

## 6. The Access Grid (READ + write, per role)

`R`ead `C`reate `U`pdate `D`elete · `p` = private-scoped · `L` = location-scoped · `—` = denied


| Resource                   | App User | Briefing Mgr | Scheduler | Super User | Tech Mgr | Flags |
| -------------------------- | -------- | ------------ | --------- | ---------- | -------- | ----- |
| **request**                | RCUD     | RCUD         | RCUD      | RCUD       | RCUD     | `p L` |
| **assetdetail**            | RCUD     | RCUD         | RCUD      | RCUD¹      | RCUD     | `p L` |
| **note**                   | **————** | R—           | RCUD      | RCUD       | RCUD     | `p L` |
| **audit**                  | **—CU—** | RCU—         | RCU—      | RCU—       | RCU—     |       |
| **presenter**              | R—       | R—           | R—        | **RCUD**   | R—       | `L`   |
| **lookupvalue**            | R—       | R—           | R—        | **RCUD**   | R—       | `L`   |
| **location**               | R—       | R—           | R-UD      | **RCUD**   | R-UD     |       |
| **locationcalendar**       | R—       | R—           | RCUD      | RCUD       | RCUD     |       |
| **locationuser**           | R—       | R—           | R-UD      | **RCUD**   | R-UD     |       |
| **locationparameter**      | R—       | R—           | R—        | **R-UD**   | R—       |       |
| **assetmaster**            | R—       | R—           | R—        | **RCUD**   | R—       |       |
| **requestTypeActivity**    | R—       | R—           | R—        | **RCUD**   | R—       |       |
| **notification**           | R—       | R—           | R—        | **RCU—**   | R—       |       |
| **attendees**              | RCUD     | RCUD         | RCUD      | RCUD       | RCUD     |       |
| **requestactivity**        | RCUD     | RCUD         | RCUD      | RCUD       | RCUD     |       |
| **requestactivityday**     | RCUD     | RCUD         | RCUD      | RCUD       | RCUD     |       |
| **requestTechnicalDetail** | RCUD     | RCUD         | RCUD      | RCUD       | RCUD     |       |


¹ Super User has **no `p`** on `assetdetail` → sees private assets too (admin bypass).

### What the grid tells you (the patterns)

1. **READ is nearly universal.** Almost every role reads almost everything. So at the
  *resource-type* level there's barely any difference in what you can **see**. The
   differentiation is in **writes** (C/U/D) and the **two flags**.
2. `**L` (location) is the real read boundary.** It rides on the high-value data —
  `request`, `note`, `presenter`, `assetdetail`, `lookupvalue`. Everyone has `R`, but
   location-sensitivity means you only see rows for **your** locations. → *This is the
   most important filter for us.*
3. `**p` (private) gates ownership.** Private `request`/`note`/`assetdetail` rows are
  visible only to their creator — except privileged roles (Super User on assets) that
   bypass it.
4. **Role personalities:**
  - **Super User** — power role: only one that creates/deletes master/config data;
   bypasses `p`.
  - **Application User** — most locked-down: *no* `note` access, can't read `audit`.
  - **Scheduler / Tech Manager** — operational mid-tier: manage locations & notes,
  read-only on master config.
  - **Briefing Manager** — close to App User on writes.
5. **Transactional sub-data** (`attendees`, `requestactivity`*, `requestTechnicalDetail`)
  is full RCUD for everyone. The control is on *which request you reach* (via `request`'s
   `p L`), not its parts.

---

## 7. The Row-Level Filters (SQL restrictions)

Only **4 rows** exist, all for the **Scheduler** role on `REQUEST`:

```sql
( ( this_.created_by = '$loggedInUser' AND lower(this_.state) = LOWER('INITIALIZED') )
  OR this_.state not in ('INITIALIZED') )
```

**In plain English:** *"You can see a request if it's in INITIALIZED (draft) state AND you
created it — OR if it's in any non-draft state."*
i.e. you see **your own drafts + everyone's confirmed events**.

Note the `**$loggedInUser` placeholder** — the briefing app substitutes the caller's
identity at query time. This is exactly the pattern our service would copy.

---

## 8. How This Maps to Our Service (read-only)

Since this service **only reads**, the whole model collapses to three questions per
resource:


| Question                        | Source                      | OpenSearch filter to inject                    |
| ------------------------------- | --------------------------- | ---------------------------------------------- |
| Can this role read it at all?   | `READ_ACCESS`               | none / block entirely (e.g. App User → `note`) |
| Is it location-sensitive (`L`)? | `LOCATION_SENSITIVE`        | `terms` on the user's location ids             |
| Is it private (`p`)?            | `PRIVATE_ACCESS`            | `isPrivate=false OR createdBy=<user>`          |
| Any row rule?                   | `SQL_RESTRICTION.SQL_QUERY` | translated `bool` clause                       |


All `C`/`U`/`D` flags are irrelevant to us — they only govern writes.

**Field mapping (SQL → OpenSearch):** the restriction fields exist on both sides —
`created_by` ↔ `createdBy`, `state` ↔ `state`, location ↔ `location.data.locationId`. So
translation is feasible, but it **must mirror the briefing app's logic faithfully** or our
results will diverge from what users see there.

**Enforcement flow:**

```
role_id (from header / user→role lookup)
  ├─ BI_ROLE_DATA_ACCESS_MAP[role]      → resources + L/p flags
  ├─ BI_ROLE_DATA_SQL_RESTRICTION[role] → row WHERE strings
  └─ compiler: flags + SQL → list of OpenSearch bool.filter clauses
                             (substitute $loggedInUser + user's location list)
  → inject in opensearch_client.search()  (AND-ed under the LLM's query)
```

---

## 9. Answers to the Open Questions (resolved by live inspection)

### ⭐ The headline finding: a role is NOT global — it's per `(user, category)`

`M_USER_ROLE` (625 rows) maps **user → role**, but **scoped by `CATEGORY_ID`**
(563/625 rows carry one). A single user holds **different roles in different categories**:


| user      | distinct roles | categories | total rows |
| --------- | -------------- | ---------- | ---------- |
| 500008051 | 5              | 45         | 133        |
| 13        | 5              | 44         | 99         |
| 10        | 1              | 33         | 41         |


So a user can be a **Scheduler in category A but only a Requester in category B**. The
access decision is `**(email, category_id) → role`**, not `email → role`.

**Why this matters hugely for us:** `category_id` already arrives in our request headers
(`x-cloud-categoryid`, see `api.py` ~line 124). And "category" here is the
location/briefing-center scope — it **is** the `LOCATION_SENSITIVE` dimension. So the
linchpin we worried about (user → locations) is *already solved by the incoming header* +
this table. The resolution is:

```
(x-cloud-user email, x-cloud-categoryid)  →  M_USER_ROLE  →  role_id for THIS category
```

### 1. User → location mapping → SOLVED

There's no `locationuser` physical table — **location ≈ category**, and the user's
category scope lives in `M_USER_ROLE.CATEGORY_ID`. The active category comes in the header.

### 2. User → role mapping → SOLVED

`M_USER_ROLE` (`USER_ID, ROLE_ID, CATEGORY_ID, CATEGORY_TYPE_ID, REQUEST_MASTER_ID, IS_DEFAULT`). A user has **many** roles, one per category (and `REQUEST_MASTER_ID` lets a
role even be scoped to a *single event*). Roles actually in use, by assignment count:


| count | role              | type   |
| ----- | ----------------- | ------ |
| 335   | Requester         | event  |
| 99    | Support User      | event  |
| 83    | Super User        | global |
| 52    | Scheduler         | global |
| 22    | Technical Manager | global |
| 18    | Briefing Manager  | global |
| 2     | Application User  | global |
| 1     | Event Manager     | event  |


### 3. The "7 missing roles" → SOLVED

They split cleanly:

- **Role hierarchy** (`PARENT_ID`) links the 5 global roles into a tree:
`Super User → Scheduler → {Briefing Manager → Application User, Technical Manager}`.
- `**CRM_USER`** — standalone global role, no data-access rows (likely API/integration use).
- **The 6 event-scoped roles** (`IS_EVENT_ROLE=1`: Event Manager, Presenter, Requester,
Super Admin, Executive Scheduler, Support User) use a **separate table** —
`M_EVENT_ROLE_DATA_ACCESS_MAP` (59 rows, resources `REQUEST`, `LOCATION`, `REQUEST_DATA`).
That's why they're absent from `BI_ROLE_DATA_ACCESS_MAP`. **Requester is the most common
role of all (335)** — so this event-role table is NOT optional; we must read it too.

### 4. Tenant scoping

Everything is keyed by `TENANT_ID`. The caller's tenant comes via `x-cloud-customerid`
(already in headers). Confirm the header→tenant_id resolution, but the plumbing exists.

### 5. Where the role comes from at request time

The briefing app does **not** appear to send a role header today — only `email` +
`categoryid` + `customerid`. So **this service must look it up**: `M_USER_ROLE` keyed by
`(user, category)`. (Cleaner long-term: have the briefing app inject the resolved role, but
the lookup is straightforward.)

---

## 10. The REAL row-filter table (better than the SQL one)

§7 covered `BI_ROLE_DATA_SQL_RESTRICTION` (4 raw-SQL rows). There's a cleaner, richer one:
`**BI_ROLE_REQUEST_ACCESS_MAP` (45 rows)** — structured `property in value` filters, far
easier to translate to OpenSearch. The **distinct** rules:


| Role                                       | Rule (combined with OR)                                                                                           |
| ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| **Application User**                       | `REQUEST.createdBy = $loggedInUser` **OR** `REQUEST.hostEmail = $loggedInUser`                                    |
| **Briefing Manager**                       | `REQUEST.createdBy = $loggedInUser` **OR** `REQUEST.hostEmail = $loggedInUser` **OR** `REQUEST.state = CONFIRMED` |
| Super User / Scheduler / Technical Manager | *(no row rule — see everything within their category scope)*                                                      |


Plain English:

- **Application User** → only requests they **created or host**. Tightest scope.
- **Briefing Manager** → their own/hosted requests **plus all confirmed** ones.
- **Super User / Scheduler / Tech Mgr** → no per-row restriction; bounded only by category.

These translate trivially to OpenSearch (`$loggedInUser` → caller email):

```json
// Application User on request:
{ "bool": { "should": [
    { "term": { "createdBy.keyword": "<email>" } },
    { "term": { "eventFormData.VISIT_INFO.oracleHostEmail.keyword": "<email>" } }
] } }
```

---

## 11. Updated Enforcement Flow (with answers folded in)

```
headers: x-cloud-user (email), x-cloud-categoryid, x-cloud-customerid
   │
   ├─ M_USER_ROLE[(user, category)]            → role_id for THIS category
   │                                             (+ tenant from customerid)
   ├─ BI_ROLE_DATA_ACCESS_MAP[role]            → which resources + L/p flags
   ├─ BI_ROLE_REQUEST_ACCESS_MAP[role]         → row rules (property in value)   ← main
   ├─ BI_ROLE_DATA_SQL_RESTRICTION[role]       → extra raw-SQL rules (rare)
   └─ M_EVENT_ROLE_DATA_ACCESS_MAP[role]       → for the 6 event roles (e.g. Requester)
        │
        ▼  compiler: substitute $loggedInUser=email, scope to category
        list of OpenSearch bool.filter clauses
   → inject in opensearch_client.search()  (AND-ed under the LLM's query)
```

**Caching note:** these tables are small and change rarely — load the role→rules map into
memory (refresh periodically) rather than hitting Oracle on every query.

---

## Quick Reference — tables to query yourself

```sql
-- roles
SELECT id, name, is_event_role, parent_id FROM BI_ROLE ORDER BY id;

-- resource permissions for a role
SELECT resource_name, read_access, create_access, update_access, delete_access,
       private_access, location_sensitive
FROM   BI_ROLE_DATA_ACCESS_MAP WHERE role_id = :role_id;

-- row-level filters: the MAIN one (structured property/value)
SELECT role_id, resource_name, property_name, operation, property_value
FROM   BI_ROLE_REQUEST_ACCESS_MAP;

-- row-level filters: the raw-SQL one (rare, 4 rows)
SELECT role_id, resource_name, operation, sql_query
FROM   BI_ROLE_DATA_SQL_RESTRICTION;

-- user → role, scoped by category (the access key is (user, category))
SELECT user_id, role_id, category_id, category_type_id, request_master_id, is_default
FROM   M_USER_ROLE WHERE user_id = :user_id;

-- event-role access (for Requester/Presenter/etc. — IS_EVENT_ROLE=1)
SELECT role_id, resource_name FROM M_EVENT_ROLE_DATA_ACCESS_MAP;
```

