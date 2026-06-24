# BriefingIQ API & Data Model — Engineering Knowledge

Everything we've reverse-engineered about how BriefingIQ stores and writes data,
so we can automate against it (agenda push, catering, etc.). Built from: the UI's
own network requests, the live Oracle DB, and the OpenSearch mirror.

Last updated: 2026-06-08

---

## 1. The two databases

| DB | Role | We use it for |
|----|------|---------------|
| **Oracle** (`ORACLE_CONNECTION_URI`, schema `BIQ_EIQ_AURORA`) | **Source of truth** — all transactional writes land here via BriefingIQ REST APIs | Mining the data model (journeys, forms, masters); a few direct reads (`m_request_master`, EBD docs) |
| **OpenSearch** (`vpc-biq-el-…`, indices `events`, `activities`) | **Denormalized search mirror** of Oracle, re-synced periodically | Almost all our read/search/report/agenda tooling |

Writes → Oracle (REST). Reads/search → OpenSearch. A reindex re-syncs Oracle → OpenSearch (we've seen counts swing during one).

---

## 2. The core mental model: everything is a FORM

BriefingIQ is form-driven. Each screen/section is a **form** (a UUID + a set of
fields). Data is stored generically as **form-data**, keyed by `{formId} + {entityId}`.

Forms are organized in a hierarchy:

```
MODULE            (e.g. "Catering", "Agenda")  — moduleType = JOURNEY
  └── JOURNEY     (e.g. "Catering", "Agenda")
        └── PAGE  (e.g. "Catering", "Agenda")   — a tab in the UI
              └── FORM (e.g. "EBC / VEBC - Catering", "Topic")  — a fillable sheet
                    └── form-data  (what you wrote, per entity/activity)
```

So **every form-data save needs to know: which form, which page, which journey, which module.**
That's why a topic save body carries `formId + pageId + journeyId + moduleId`.

**Discovery endpoint:** `GET /modules/{moduleId}/configs/details`
→ returns the whole `module → journeys → pages → forms` tree (each form has
`uniqueId`, `formName`, `formTypeId`). This is the clean, dynamic way to resolve
form IDs per tenant instead of hardcoding.

---

## 3. Entity hierarchy (the business data)

```
LOCATION (resourceType=Location)
  ├── ROOMS (resourceType=Room) ── each has a calendar (bookings + blocks)
  └── EVENTS (CBR-… ; in OpenSearch `events` index)
        ├── eventFormData{}  ← EVENT-level forms: VISIT_INFO, Opportunity,
        │     EXTERNAL/INTERNAL_ATTENDEES, VISIT_SUMMARY, CATERING,
        │     VIRTUAL_CONNECTION, DOCUMENT
        └── ACTIVITIES (sessions; OpenSearch `activities` index)
              activityType = TOPIC_ACTIVITY | CATERING
              └── activityData{}  ← ACTIVITY-level child forms:
                    topic, topic_presenter, CATERING
```

- **Event id forms:** the events index `eventId` is CBR-style; the **UUID** lives at
  `eventFormData.VISIT_INFO.eventId` (used as `CURRENT_EVENT` for activity scoping).
- **Masters** = shared catalogues (e.g. Topics). Stored in Oracle `M_TENANT_MASTER`,
  typed by `MASTER_TYPE_ID`. Topics are `master_type 56` (`UNIQUE_ID B147B2E9-…`,
  name "Topic"). Topics are hierarchical via `PARENT_ID` (both parent and child
  topics are valid references).

---

## 4. Write APIs

Base: `https://briefings.briefingiq.com/events/api`

### Common headers (sent on every call)
`Authorization: Bearer <token>`, `x-cloud-eventid`, `x-cloud-customerid`,
`x-cloud-categoryid`, `x-cloud-categorytypeid`, `x-cloud-context/requested/client-timezone`,
`x_cloud_user`. **Form-data saves also need `x-cloud-activityid: <activityId>`**
(backend resolves the parent activity from it).

### Agenda push (per session) — ✅ WORKING
| # | API | Body (key fields) | Status |
|---|-----|-------------------|--------|
| 1 | `POST /activities` | `eventId, startTime, endTime, duration, activityDayId, resourceId, activityType` → returns `activityId` | ✅ |
| 2 | **`POST /forms/{TOPIC_FORM}/data`** | `{moduleId, formId, journeyId, pageId, id:"", parentId:activityId, childs:[], files:[], data:{textField2:<topicUniqueId>, textAreaField1:objective, textAreaField2:optional}}` | ✅ |
| 3 | `POST /forms/{PRESENTER_FORM}/data` | `{moduleId, formId, journeyId, pageId, parentId:activityId, data:{textField2:email, textField3:title, textField1:"Accepted"}}` | ✅ (POST = create) |

**Key:** form-data writes are **createFormData via POST** (`id:""`, `parentId`).
`PUT /forms/{form}/data/{id}` is **updateFormData** and needs a pre-existing record —
a fresh activity has none, so PUT → `save(null)` → 500 (see §6).

### Masters (topic catalogue)
- `GET /mastertypes/{MASTERS_TYPE_ID}/masters?fetchType=HIGHER_LEVEL` — fetch the
  **valid** topic tree (what the UI dropdown uses; only resolvable topics). Calling
  it without `fetchType` returns stale/child rows whose uniqueIds don't resolve.
- `POST /mastertypes/{MASTERS_TYPE_ID}/masters` — create a new topic

### Rooms / scheduling
- `GET /events/{eventId}/eventresources` — rooms for an event
- `GET /resourcetypes/{ROOM_TYPE_ID}/resources?fetchType=HIERARCHY_LEVEL` — tenant rooms
- `GET /resources/{resourceId}/calendars` — a room's bookings (conflict checks)
- `POST /resources/{resourceId}/calendars` — block/hold a room

---

## 5. Known IDs (this tenant: Crowdstrike, tenant_id=2)

⚠️ These are **hardcoded today** and should be resolved dynamically via
`/modules/{id}/configs/details`. Several are **hand-seeded non-UUID strings** (e.g.
`…-3421-DFCS-ERDW-5E8B8F0B9081`), so they may differ per tenant/environment.

| Name | ID | Source / status |
|------|----|-----------------|
| Module (briefings) | `BFF04CFD-87A4-4CDA-9B76-612A82C8FE5C` | matches UI topic save |
| Topic container form (`TOPIC_ACTIVITY`) | `5622B58C-55BA-4473-9B3A-38D732DDD04B` | activity slot form |
| **Topic data form** | `3422EREW-3421-DFCS-ERDW-5E8B8F0B9081` | from UI's topic PUT (seeded, non-UUID) |
| Presenter form | `ACED1483-82F1-4E30-B4C3-2259338B4EAE` | ✅ verified — UI add-presenter POSTs here |
| Catering form | `221DEREW-3421-DFCS-ERDW-5E8B8F0B9081` | from `/config/details` (Catering module) |
| Masters type "Topic" | `B147B2E9-053D-44F9-85F5-914B9F817FEA` | ✅ Oracle: = master_type 56 "Topic" |
| Room resource type | `EAC8F953-99D0-43DF-8E15-CA03F21EA92D` | |
| **Agenda** journey | `30a1a47e-6b80-11f0-9e02-325096b39f47` | ✅ Oracle `M_JOURNEY` "Agenda" (tenant 2) |
| **Agenda** page | `e98faa08-6b80-11f0-a966-325096b39f47` | ✅ Oracle `M_PAGE` "Agenda" |
| Catering journey | `32b207ea-6b80-11f0-8f3c-325096b39f47` | `/config/details` |
| Catering page | `eb86a5b4-6b80-11f0-8672-325096b39f47` | `/config/details` |

---

## 6. ROOT CAUSE (SOLVED): topic save must be POST (create), not PUT (update)

**Symptom:** topic save → HTTP 500
`InvalidDataAccessApiUsageException: Entity must not be null` (Hibernate `save(null)`).
Sessions create fine (blocks appear) but have no topic → "nameless time blocks".

**Actual root cause** (found via the full stack trace — see below):
```
com.alliance.biq.event.form.data.handler.DefaultFormHandler.updateFormData(DefaultFormHandler.java:119)
  → repository.save(<null>)
```
`PUT /forms/{form}/data/{activityId}` routes to **`updateFormData`**, which looks up
an **existing** form-data record and updates it. A freshly-created activity has **no
topic form-data record yet** → the lookup returns null → `save(null)` → 500.

**Fix:** use **`POST /forms/{form}/data`** (`createFormData`) with `id:""` + `parentId`
— this creates the record. Verified 200 against the live API via the local harness.
(The UI's PUT worked only because opening the topic modal had already created/loaded
the record first.)

### How it was finally diagnosed
The Lambda logs **truncated** the stack trace at generic Spring frames, hiding
`updateFormData`. We burned ~8 deploys fixing real-but-unrelated things. A **local
test harness** (`test_push_local.py`, gitignored) that calls the writer functions
directly against prod with a DevTools token gave us (a) the full trace and (b)
seconds-per-iteration — and proved PUT(500) vs POST(200) in 2 tries.
**Lesson: get the full error + a fast local repro before deploying on hypotheses.**

### Other fixes made along the way (all correct — keep them)
- `_fetch_topics` uses `…/masters?fetchType=HIGHER_LEVEL&size=1000` (+ flattens
  nested children) → only sends **resolvable** topic uniqueIds. Without it we'd
  send stale/child IDs absent from `M_TENANT_MASTER`. (Not the 500 cause, but a
  real correctness bug that would bite once activities exist.)
- `_set_topic` / `_add_presenter` send the `x-cloud-activityid: <activityId>` header.
- Form/journey/page ids resolved dynamically via `/modules/{id}/configs/details`
  (`_resolve_agenda_config`) — no longer hardcoded.

**Status: FIXED + verified live via local harness. Pending deploy to Lambda.**

---

## 7. Oracle tables worth knowing (schema `BIQ_EIQ_AURORA`)

| Table | Holds |
|-------|-------|
| `M_MODULE` / `M_MODULE_JOURNEY` | modules and their journeys |
| `M_JOURNEY` | journey definitions (`UNIQUE_ID`, `JOURNEY_NAME`) |
| `M_PAGE` / `M_JOURNEY_PAGE` | page definitions |
| `M_PAGE_FORM` | which forms live on which page (`PAGE_ID`, `FORM_ID`, `FORM_NAME`) |
| `M_FORM` / `M_FORM_FIELDS` / `M_FORM_SECTION` | form templates + their fields |
| `M_MASTER_TYPE` | master catalogue types (Topic = id 56, `B147B2E9-…`) |
| `M_TENANT_MASTER` | the actual master rows (topics, etc.) — `UNIQUE_ID`, `PARENT_ID`, `TEXT_FIELD_1=name`, `MASTER_TYPE_ID` |
| `M_REQUEST_MASTER` | events; `unique_id`/`id` ↔ `event_number` (CBR-…) |
| `T_EVENT_MODULE_JOURNEY` / `T_JOURNEY_PAGE` | per-event journey/page *instances* (sparse) |

Note: tables exist under many schema owners (env copies: `AURORA`, `AURORA_V1`,
`AURORA_PROD_V1`, `DEMO_DS`, `NEBULA`, …). `BIQ_EIQ_AURORA` is our connection's
default and holds live data.

---

## 8. TODO / hardening
- [ ] Fix topic save 500 (headers — §6)
- [ ] Resolve form/journey/page IDs **dynamically** via `/modules/{id}/configs/details` (drop hardcoded IDs)
- [ ] Build catering push: `POST /activities` (activityType=CATERING) + `PUT /forms/221DEREW…/data/{id}` for lunch/break sessions
- [ ] Verify presenter add end-to-end
- [ ] Make journey/page lookup multi-tenant (by name "Agenda" via `M_JOURNEY`/`M_PAGE`)
