# BriefingIQ API — Field Guide (verified reality vs. the spec)

Everything below was verified live against `briefings.briefingiq.com` (July 2026)
or extracted from the JMeter data-population plan (`BIQ_fixed_cleaned.jmx`),
which is the closest thing to a source of truth for write payloads.

## TL;DR — how much to trust the Swagger spec

| Use case | Trust level |
|---|---|
| Discovering endpoints (what exists, paths, params) | ✅ Good — all 211 GETs behaved as documented |
| Read (GET) payloads/responses | ✅ Good |
| Write (POST/PUT) payloads | ⚠️ Unreliable — hand-written examples that drift (wrong types, missing required fields, wrong module for this tenant) |
| Understanding the EBC briefing flow | ❌ Misleading — the meetings examples are for the *tradeshow* module, not EBC briefings |

Spec drift caught live: `POST /events` example shows `startDate` as a string —
server demands a CloudDate object; `eventFormat` is required but undocumented;
`POST /events/{id}/meetings` documents a JSON response but returns an empty 200
**and silently creates nothing** on EBC events.

## The core mental model

**In this tenant, a briefing IS an event** — category `Customer Briefing Request`
(`REQUEST_TYPE`), event numbers like `CBR-20260717-092`. It is *not* a "meeting"
(that subsystem belongs to the tradeshow module — NRF booth meetings etc.).

Briefings are created through the **forms engine**, not `POST /events`:
the UI (and JMeter) submit form *data* and the server creates the CBR event
as a side effect.

## Tenant constants (this environment)

| Thing | Value |
|---|---|
| Customer (tenant) id | `131393dd-0449-4cca-8528-2fed6b79eaed` |
| Category type | `CATEGORY_TYPE_BRIEFINGS` |
| Workspace category ("Briefings") | `72DCAF42-C7C0-4006-8F31-7952185E5D61` |
| Request category ("Customer Briefing Request") | `D06189A1-69AF-4D17-AC5B-480F7589D427` ← use this as `x-cloud-categoryid` for the create flow |
| "New Request" module (REQUEST_CREATION) | `E6AC55C4-9BDC-4B5F-BE07-A6F5FBD7E75A` |
| Create-request form ("EBC - New Request - Customer Briefing") | `49E1FC02-7EAA-456E-B37F-BD5543B49165` |
| Topic module | `BFF04CFD-87A4-4CDA-9B76-612A82C8FE5C` |
| Topic form | `5622B58C-55BA-4473-9B3A-38D732DDD04B` |
| Presenter form | `ACED1483-82F1-4E30-B4C3-2259338B4EAE` |
| Room resource type | `EAC8F953-99D0-43DF-8E15-CA03F21EA92D` |

Don't hardcode in new code — resolve at runtime (IDs differ per tenant):
`GET /admin/moduleaccess` → module by `moduleType=REQUEST_CREATION` →
`GET /modules/{moduleId}/configs` → `{journey, page, form}` →
`GET /forms/{formId}` → field definitions.

## Required headers (every call)

```
Authorization: Bearer <user session token>     ← the real auth; server derives identity
x-cloud-customerid, x-cloud-categoryid, x-cloud-categorytypeid
X-Cloud-Client/Context/Requested-Timezone
X_cloud_user: <email>                          ← context hint only, not proof of identity
x-cloud-eventid: <requestId>                   ← after creation, for request-scoped calls
```

RBAC is enforced server-side per request (401 no token, 403 forbidden), so
forwarding the user's own token means results respect their permissions.

## The briefing lifecycle (from JMeter, in execution order)

```
1. CREATE REQUEST
   POST /forms/{requestFormId}/data
   {
     "moduleId":  "<New Request module>",
     "formId":    "<create-request form>",
     "journeyId": "<from module configs>",
     "pageId":    "<from module configs>",
     "data": {
       "duration":   1,                                  // NUMBER (1–5)
       "startDate": {"isoDate": "2026-07-24"},           // CLOUD_DATE
       "startTime": {"isoDate": "2026-07-24T10:00:00"},  // CLOUD_TIME
       "endTime":   {"isoDate": "2026-07-24T11:00:00"},  // CLOUD_TIME
       "textField1": "Customer Name",                    // required
       "textField2": "Primary Opportunity ID",           // required
       "textField3": "..."                               // optional
     }
   }
   → response contains requestId (the new CBR event) + initial status

   Field types → JSON encoding: CLOUD_DATE/CLOUD_TIME → {"isoDate": ...},
   CHECKBOX → boolean, NUMBER → int, multi-select RESOURCE/MASTER → array.
   Field names/types come from GET /forms/{formId} (formUIConfig JSON) +
   GET /forms/{formId}/fieldmappings.

2. ROOMS
   POST /events/{requestId}/eventresources
   then room-assignment via POST /forms/{roomFormId}/data

3. PRESENTERS
   POST /resourcetypes/{presenterResourceTypeId}/resources

4. AGENDA / ACTIVITIES (topics, catering, breaks…)
   POST /activities                       → time slot (activityId)
   POST/PUT /forms/{activityFormId}/data  → attach topic/details to slot

5. PARTICIPANTS
   POST /forms/{participantFormId}/data

6. DOCUMENTS
   POST /forms/{formId}/documents

7. STATE TRANSITION (submit/confirm/hold…)
   GET the request data → available actions are the keys of `_links`
   PUT /forms/{requestFormId}/data/{requestId}/actions/{ACTION}?sendNotification=false
   (JMeter targets CONFIRM / HOLD / WAITLIST; excludes RESCHEDULE, SAVE, etc.
    Keep sendNotification=false in tests to avoid email blasts.)
```

Edits to an existing briefing follow the same pattern:
`PUT /forms/{formId}/data/{formDataId}` (read-modify-write of `data`),
plus the dedicated endpoints for rooms/activities.

## Known issues / gotchas (as of 2026-07-17)

1. **Create-request API is currently broken upstream** — returns HTTP 500
   `NonUniqueResultException: query did not return a unique result: 601` even
   with a correct payload (platform team is aware). JMeter hits the same wall.
   Re-verify the create flow once their fix lands.
2. `POST /events/{id}/meetings` on a CBR event: **HTTP 200, empty body, creates
   nothing**. Don't interpret 200 as success — check for a body/meetingId.
3. Some spec'd endpoints aren't deployed to prod (404 from Tomcat), e.g.
   `/locationtypes`, `/locations` — they exist only on dev.
4. CloudDate fields: GETs return `{utcMs, zoneId, zoneDate, zoneTime, ...}`;
   form-data writes want `{"isoDate": "..."}`. `POST /events` (don't use it for
   briefings) wants the object form, not a raw epoch number.
5. The Swagger specs are publicly downloadable without auth at
   `https://api.briefingiq.com/*.yaml` (minor exposure, flagged to platform team).

## Where this knowledge lives in code

- `data/briefingiq_api_catalog.json` — 211 read-only endpoints (agent-searchable);
  regenerate with `scripts/build_api_catalog.py`
- `tools/api_catalog.py` — catalog search + generic allowlisted GET executor
- `tools/briefing_builder.py` — draft → confirm → push (push being reworked to
  the forms flow above; blocked on upstream create bug)
- `tools/briefing_editor.py` — surgical edits to existing briefings
- `tools/briefingiq_writer.py` — agenda/topic/presenter/calendar writes
  (already uses the forms pattern)
- `BIQ_fixed_cleaned.jmx` (repo root) — JMeter population plan; the reference
  for write payloads and call ordering
