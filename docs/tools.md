# Agent Tools Reference

Brief description of every tool available to the AI agent.

---

## Agenda & Presenters

### `generate_agenda`
Generates an EBC-style agenda for a meeting. Pass `event_id` **or** `company_name`. Internally: resolves the event from OpenSearch, pulls similar past briefings, calls the presenter suggestion engine, and uses an LLM to write the sessions.

### `suggest_presenters`
Returns ranked presenter recommendations. Pass at least one of: `event_id`, `topic`, `industry`, `customer_name`.  
Flow: customer/industry → events index for event_ids → activities index filtered by event_ids + topic → ranked by accepted sessions → recency.  
Falls back to global top-200 most recent activities if scoped search returns 0.

### `push_agenda_to_briefingiq`
Pushes AI-generated sessions into BriefingIQ as calendar activities.  
**Must** call `get_event_rooms` first, then call this only after user confirms.  
Params: `event_id`, `event_date` (YYYY-MM-DD), `sessions[]` (title + time_slot), optional `resource_id`, optional `presenter_emails[]`.

### `get_event_rooms`
Fetches available rooms (resource_ids + names) for a BriefingIQ event. Call before `push_agenda_to_briefingiq`.

---

## Scheduling

### `schedule_meeting`
Creates blocked calendar time on a BriefingIQ resource calendar.  
Params: `calendarFromDateIso`, `calendarStartTimeIso`, `calendarEndTimeIso`, `calendarToDateIso` — all ISO-8601 strings. Optional `calendarType` (default `BLOCKED`) and `comments`.

---

## OpenSearch

### `search_opensearch`
General-purpose OpenSearch query. Takes a raw DSL body (`dsl_query`) and optional `index`.  
- Default index → `events` (event-level: attendees, status, location, opportunity)  
- `index: "activities"` → per-session data (topics, presenters, rooms, catering)  
- Returns hits; pair with `format_chart` or `generate_report` for display.

### `count_opensearch`
Returns a document count. Use for "how many" questions. Takes a `query` object (the inner query clause, not wrapped) and optional `index`.

### `list_indices`
Lists all OpenSearch indices with health, doc count, and store size. Optional `index` pattern filter (e.g. `events*`).

---

## Visualisation & Output

### `format_chart`
Formats data into a Highcharts config for frontend rendering.  
Types: `bar`, `column`, `line`, `pie`, `area`, `spline`, `areaspline`, `heatmap`, `xrange`.  
Call **after** `search_opensearch` returns data.

### `generate_report`
Builds a table/grid from an OpenSearch query. Use only when user explicitly asks for a report/table.  
Params: `dsl_query`, `columns[]` (binding + header), `title`, optional `index`.  
Column bindings: `event_name`, `customer_name`, `status`, `location_name`, `event_start_time`, `presenter_name`, `topic_name`, etc.

### `generate_pdf`
Generates a downloadable PDF from text content.  
Params: `content` (full text), `title`.

---

## Utilities

### `get_time_context`
Returns current time and epoch-ms day boundaries for date filtering. Use before time-sensitive queries (`today`, `next N days`).  
Params: optional `date_iso`, `days_ahead`, `timezone` (IANA).

---

## Disabled

### `query_database` *(disabled)*
Oracle DB query tool — temporarily disabled, all structured queries now go through OpenSearch.

---

## Key OpenSearch Field Paths

| Index | Field | Purpose |
|-------|-------|---------|
| `events` | `eventData.VISIT_INFO.data.customerName` | Company name |
| `events` | `eventData.VISIT_INFO.data.customerIndustry` | Industry |
| `events` | `eventData.VISIT_INFO.data.eventName` | Event name |
| `activities` | `activityInfo.topic_presenter.data.presenter.primaryEmail` | Presenter email (exists filter) |
| `activities` | `activityInfo.topic_presenter.data.presenter.firstName/lastName` | Presenter name |
| `activities` | `activityInfo.topic_presenter.data.presenterStatus` | Status (skip: declined/rejected/cancelled) |
| `activities` | `activityInfo.topic.data.topic.textField1` | Session topic name |
| `activities` | `startTime.utcMs` | Session start time (epoch ms) |
| `activities` | `eventId` | Links activity → event |
