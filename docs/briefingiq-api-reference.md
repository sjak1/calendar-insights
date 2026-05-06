# BriefingIQ API Reference

Endpoints from the BIQ EIQ New Features Swagger spec (`biq-eiq-new-features.yaml`).
Base URL: `https://briefings.briefingiq.com/events/api` (prod) / `https://dev.briefingiq.com/event/api` (dev)

Verified via direct curl probes on 2026-04-15 against the live tenant.

---

## Currently Used

| Endpoint | Used In | Notes |
|----------|---------|-------|
| `GET /resourcetypes/{ROOM_TYPE}/resources?fetchType=HIERARCHY_LEVEL` | `list_rooms` | **Must include `fetchType=HIERARCHY_LEVEL`** or response is empty |
| `GET /events/{eventid}/eventresources` | `fetch_event_rooms` | Rooms assigned to a specific event |
| `GET /resources/{resourceid}/calendars` | `get_resource_schedule` | Existing bookings on a room |
| `POST /resources/{resourceid}/calendars` | `block_calendar` | Block/reserve a room |
| `POST /activities` | `push_agenda_to_app` | Create agenda session |
| `PUT /forms/{formid}/data/{formdataid}` | `push_agenda_to_app` | Set session topic |
| `POST /forms/{formid}/data` | `push_agenda_to_app` | Add presenter to session |

---

## Probed & Verified Working (Not Yet Used)

### `GET /activities?view=calendar`

Calendar view of activities (bookings) across resources, scoped by a parent Location UUID.

**Required query params:**
- `startDate` — epoch **milliseconds** (Long, not ISO string)
- `endDate` — epoch milliseconds
- `resourceTypeId` — e.g. `EAC8F953-99D0-43DF-8E15-CA03F21EA92D` for Room
- `parentId` — Location UUID (e.g. `26C5712B-4520-421A-B41D-08A030F62B37` for Redwood Shores)

**Status:** 200 OK with empty result for an unbooked window. Accepts `view=calendar`.

**Potential use:** Replace per-room calls to `get_resource_schedule` when we want all room bookings for a Location in one request. Useful for "what's free this week across all rooms" queries.

### `GET /resources/{resourceid}/hours`

Working hours for a specific resource.

**Status:** 200 OK but `totalElements: 0` for the SkyDeck room — data is opt-in, most rooms don't have it set. Keep the hardcoded 9–18 fallback in `find_vacant_slots`.

---

## Dead Ends — Do Not Use

| Endpoint | Why |
|----------|-----|
| `GET /resourcetypes/{id}/resources/calendar` | NPE in `EventResourceSearchFactoryImpl.getResourceHandler` regardless of query params. Not used by frontend either. |
| `GET /events/{id}/meetinglocations` | NPE in `EventLocationSearchHandlerFactory.getLocationHandler`. With `type=VACANT` gets past factory but hits `SQLGrammarException`. Frontend doesn't call it. |

---

## Other Endpoints to Explore Later

### Meetings (Sessions/Activities)

| Endpoint | Purpose |
|----------|---------|
| `GET /events/{eventid}/meetings` | List meetings for event |
| `POST /events/{eventid}/meetings` | Create a meeting/session |
| `PUT /meetings/{meetingid}/actions/RESCHEDULE` | Reschedule a meeting |
| `PUT /meetings/{meetingid}/actions/{actionid}` | Update meeting status |
| `GET /meetings/{meetingid}/history` | Meeting change history |
| `GET /meetings/{meetingid}/notes` | Meeting notes |
| `POST /meetings/{meetingid}/notes` | Add meeting notes |

### Presenters

| Endpoint | Purpose |
|----------|---------|
| `GET /events/{eventid}/presentercalendar` | Presenter availability for event |
| `GET /presenters/{presenterid}/calendars` | Presenter's full calendar |
| `GET /events/{eventid}/meetings/{meetingid}/presenters` | Presenters on a session |
| `PATCH /events/{eventid}/meetings/{meetingid}/presenters/{presenterid}/{status}` | Update presenter status |
| `GET /eventrequests/{requestId}/topics/{topicId}/presenters` | Presenters for a topic |

### Directory & Users

| Endpoint | Purpose |
|----------|---------|
| `GET /directory/users` | User directory lookup |
| `GET /events/{eventid}/locations/{locationid}/users` | Users at a location for an event |

---

## Key Patterns Learned

1. **`fetchType=HIERARCHY_LEVEL`** is needed to get real results from `/resourcetypes/{id}/resources`. Without it, the endpoint returns 0 rooms silently. This was the root cause of the `list_rooms` bug.

2. **Dates in `/activities` must be epoch milliseconds**, not ISO strings. The column type is `Long` — passing ISO gets a 400 with `"converted to null"`.

3. **`parentId` on `/activities` is a Location UUID**, not a category or event ID. The hardcoded `26C5712B-4520-421A-B41D-08A030F62B37` we saw last session is the Redwood Shores Location resource, and the frontend uses it to scope calendar queries.

4. **Factory-handler NPEs** (`EventResourceSearchFactoryImpl`, `EventLocationSearchHandlerFactory`) happen when query params don't match any registered handler. These endpoints are effectively dead — frontend doesn't use them.

5. **Tenant-level rooms ≠ event-level rooms.** `list_rooms` returns Outlook1-6 (tenant pool). `fetch_event_rooms` returns SkyDeck/PeakView/Outlook Plus/Outlook 7 (event-specific). Likely different Locations or per-event aliases. Keep both tools, they serve different questions.
