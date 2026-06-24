# Features — How Each One Works

A plain-language reference for every working capability: what it does, what it
runs on, and how it decides its output. No ML anywhere — everything is
OpenSearch queries + rule logic + targeted LLM calls.

Legend: ✅ working · 🟡 partial · ⬜ planned

---

## 1. Agenda Generation ✅
**What:** Generates a full briefing agenda (sessions, timings, types, strategic notes) for an event or company.
**Runs on:** `generate_agenda` → Bedrock Sonnet, fed with structured event context.
**Basis:**
- Pulls customer, industry, visit focus, meeting objective, attendee mix (C-level/decision-maker counts) from the event.
- Pulls **similar past briefings** (same industry + focus) and **previous meetings** for the same customer to seed recommendations.
- Sonnet composes the agenda from that context; output is editable before pushing.

## 2. Push Agenda → BriefingIQ ✅
**What:** Writes the generated agenda into BriefingIQ as real calendar activities.
**Runs on:** `push_agenda_to_briefingiq` → BriefingIQ REST API.
**Basis:** Per session it makes 3 calls — create time slot → set topic → (optional) add presenter. Pre-flights per-room conflicts before writing. Returns created/failed counts.

## 3. Presenter Suggestions ✅
**What:** Recommends best presenters for a topic / event / audience.
**Runs on:** `suggest_presenters` → activities index.
**Basis (ranking order):**
1. On-topic session count (topic *prefers*, doesn't hard-filter — except when topic is the only filter)
2. Accepted count (skips declined/cancelled)
3. Total sessions
4. Distinct event coverage
5. Recency
- If **audience level** (C-suite/VP/senior) is passed, parses presenter titles and pushes peer-level seniority to the top, *then* on-topic track record among peers.
- Stamps **availability** — flags anyone already booked in the target time window.
- Works 3 ways: inside an event (auto topics), by topic, or by industry/customer.
- Full mechanics: [docs/presenter-suggestions.md](docs/presenter-suggestions.md).

## 4. Room Availability & Booking ✅
**What:** Lists rooms, shows what's booked, finds free slots, books/blocks a room.
**Runs on:** `list_rooms`, `get_resource_schedule`, `find_vacant_slots`, `block_calendar`.
**Basis:**
- `list_rooms` is context-aware: inside an event → that event's rooms; otherwise → tenant-wide Outlook rooms.
- `find_vacant_slots` computes free windows within working hours (9–6, user's timezone).
- `block_calendar` runs a conflict pre-flight; overlapping bookings are returned instead of written.

## 5. Natural-Language Booking ✅
**What:** "Book Alpine room 2–4pm Thursday" → a real hold.
**Runs on:** `block_calendar` + LLM date/time parsing.
**Basis:** LLM maps natural language → ISO time in the request timezone, then the same conflict pre-flight as above.

## 6. Confirmation Email Drafts ✅
**What:** Drafts a customer-facing event confirmation (subject + body).
**Runs on:** `draft_confirmation_email` → fetches live event data → Haiku composes body.
**Basis:** Deterministic event fetch (customer, host, dates, agenda) handed to a fast Haiku sub-LLM that writes warm, professional plain-text. Pulls attendee emails for the send list.

## 7. Catering / Setup Sheets ✅
**What:** An ops sheet grouping sessions by room with inferred catering + AV needs.
**Runs on:** `draft_catering_sheet`.
**Basis:** Rule-based (not LLM, intentionally — ops output must be predictable):
- Catering: keyword match on session title ("lunch"→full catering, "coffee"→refreshments, else→water).
- Setup/AV: keyword match ("demo"→projector+screen, "roundtable"→round setup, etc.).

## 8. Search & Lists ✅
**What:** Find events/attendees/opportunities/presenters by any field.
**Runs on:** `search_opensearch` → events or activities index.
**Basis:** LLM builds OpenSearch DSL from the schema reference; filters on customer, status, location, date, industry, host, etc. Location filtering prefers `locationName`.

## 9. Reports & Tables ✅
**What:** Column/grid reports (events by status, revenue, region, etc.).
**Runs on:** `generate_report` → Wijmo-style grid config + rows.
**Basis:** LLM supplies DSL + column bindings; backend maps bindings (`customer_name`, `opportunity_revenue`, …) to schema field paths and flattens hits to rows.

## 10. Charts ✅
**What:** Bar/column/line/pie/heatmap/timeline visualizations.
**Runs on:** `search_opensearch` (aggregations) → `format_chart`.
**Basis:** Aggregation query produces buckets; `format_chart` shapes them into the requested chart type.

## 11. Counts & Summaries ✅
**What:** "How many confirmed briefings in Redwood this month?"
**Runs on:** `count_opensearch`.
**Basis:** `size: 0` + filter/aggregation; returns counts/breakdowns without payload.

## 12. PDF Export ✅
**What:** Export any report/agenda/summary as a downloadable PDF.
**Runs on:** `generate_pdf`.
**Basis:** Takes the formatted content + title, renders to PDF.

---

## Planned / High-Value Gaps

### Predefined AI Prompt Chips ⬜ (client-requested)
One-click canned queries to remove the "what do I type" friction:
1. Requests with **no agendas**
2. Requests with **no attendees**
3. Requests with **no / closed opportunities**
4. Requests with **no speaker** for agenda topics
5. Requests with **no status change in 2 weeks**

All five are plain `search_opensearch` filters — just need surfacing as buttons.

### Meeting Notes & Action Items ⬜
Transcription → summary → action items → follow-up email. Entire section unbuilt; highest "wow" feature; blocked on Zoom/Teams AI-companion decision.

### Attendee-Aware Presenter Ranking 🟡
C-level / strategic-account flags exist in data but aren't yet fed into presenter ranking signals.

### Cross-Event Conflict Detection 🟡
Current conflict check is per-room during agenda push; doesn't yet catch the same presenter double-booked across different events.
