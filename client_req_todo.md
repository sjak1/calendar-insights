# Client Requirements — Status Tracker

Tracking what's built vs pending across all the EBC AI requirements.

Legend: ✅ done | 🟡 partial | ⬜ not started

---

## 1. AI-Assisted Agenda Generator (external + internal)

| #    | Requirement                                        | Status | Notes                                                                       |
| ---- | -------------------------------------------------- | ------ | --------------------------------------------------------------------------- |
| 1.1  | Auto-generate agenda from EBC request              | ✅     | `generate_agenda` tool, Bedrock Sonnet                                      |
| 1.2  | Use customer company profile                       | ✅     | Pulled from `eventData.VISIT_INFO.data.customerName`                        |
| 1.3  | Use industry vertical                              | ✅     | Pulled from `customerIndustry`                                              |
| 1.4  | Use EBD (Executive Briefing Document)              | 🟡     | EBD fetched from DB, PDF parse needs `pdfplumber` (not installed on Lambda) |
| 1.5  | Use meeting objectives / visit focus               | ✅     | Passed into agenda prompt                                                   |
| 1.6  | Use marketing/sales plays & strategic themes       | ⬜     | No sales plays data source wired in                                         |
| 1.7  | Use attendee title level & mix                     | ✅     | C-level, decision makers, remote counts surfaced                            |
| 1.8  | Pull agenda recommendations from similar briefings | ✅     | `similar_briefings` query on past events                                    |
| 1.9  | EBC Manager review/refine flow                     | 🟡     | Generated agenda is editable, but no dedicated review UI                    |
| 1.10 | Push final agenda back to BriefingIQ               | ✅     | `push_agenda_to_briefingiq` + `get_event_rooms`                             |

---

## 2. EBC Chatbot within EIQ (Ask Oracle)

| #   | Requirement                               | Status | Notes                                                     |
| --- | ----------------------------------------- | ------ | --------------------------------------------------------- |
| 2.1 | Find presenters by topic                  | ✅     | `suggest_presenters` with topic filter                    |
| 2.2 | Parent topic / sub-focus topic matching   | 🟡     | Only topic name matched, no hierarchy parsing             |
| 2.3 | Match speaker to audience level (C-suite) | ⬜     | Attendee C-level detected, not fed into presenter ranking |
| 2.4 | Strategic account awareness               | ⬜     | No strategic-account flag in ranking                      |
| 2.5 | Chatbot inside EIQ app                    | ✅     | Whole system runs embedded in BriefingIQ                  |

---

## 3. EBC AI Meeting Notes & Action Item Generator

| #   | Requirement                         | Status | Notes                                  |
| --- | ----------------------------------- | ------ | -------------------------------------- |
| 3.1 | Live/recorded meeting transcription | ⬜     | Zoom AI Companion suggested in spec    |
| 3.2 | Key discussion summary              | ⬜     |                                        |
| 3.3 | Action items with owner attribution | ⬜     |                                        |
| 3.4 | Decision logs                       | ⬜     |                                        |
| 3.5 | Follow-up recommendations           | ⬜     | Discussed as a feature idea, not built |
| 3.6 | Post-meeting follow-up email draft  | ⬜     | Scoped out, not implemented            |
| 3.7 | Distribute to Sales/EBC/leadership  | ⬜     |                                        |
| 3.8 | Integration with BIQ                | ⬜     |                                        |

---

## 4. OCC — Smart Space & Resource Optimization

| #   | Requirement                                                     | Status | Notes                                                                                                                                                                                                       |
| --- | --------------------------------------------------------------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 4.1 | Recommend best rooms by size/setup/AV/catering                  | ⬜     | `list_rooms` returns rooms (event-aware) but no AI ranking on capacity/AV/catering                                                                                                                          |
| 4.2 | Predictive availability (peak times, booking windows)           | ⬜     |                                                                                                                                                                                                             |
| 4.3 | Conflict detection — overlapping events/double-booked resources | 🟡     | Agenda push pre-flights per-room conflicts via `get_resource_schedule` (merges activities + blocks). Cross-event / cross-room detection still pending.                                                      |
| 4.4 | Presenter double-booking check                                  | ✅     | `_check_presenter_conflicts` in `tools/presenter_suggest.py`; overlap query on activities index; `available` + `conflicts` stamped on every suggestion; wired into `agenda_generator` with event-day window |

---

## 5. OCC — Automated Calendar Management

| #   | Requirement                            | Status | Notes                                                                                         |
| --- | -------------------------------------- | ------ | --------------------------------------------------------------------------------------------- |
| 5.1 | Natural language booking               | ✅     | `block_calendar` with conflict pre-flight; LLM maps NL → ISO in request timezone              |
| 5.2 | Vacant timeslot finder                 | ✅     | `find_vacant_slots` computes free windows; `list_event_activities` surfaces what's already on |
| 5.3 | Outlook / Google calendar sync         | ⬜     |                                                                                               |
| 5.4 | Auto holds + confirm/release reminders | ⬜     | `block_calendar` creates holds; no scheduler or reminder channel wired                        |
| 5.5 | Dynamic rescheduling when events move  | ⬜     |                                                                                               |

---

## 6. OCC — Client Interaction & Booking Assistance

| #   | Requirement                        | Status      | Notes                                                                             |
| --- | ---------------------------------- | ----------- | --------------------------------------------------------------------------------- |
| 6.1 | 24/7 booking inquiry chatbot       | ✅          | Chat inside BIQ handles queries 24/7 — requirement met                            |
| 6.2 | Auto-draft event confirmations     | ✅          | `draft_confirmation_email` tool — fetches live event data, returns subject + body |
| 6.3 | Auto-draft catering/setup sheets   | in progress | `draft_catering_sheet` tool — groups sessions by room, infers AV + catering needs |
| 6.4 | Follow-up nudges for pending holds | ⬜          |                                                                                   |

---

## 7. OCC — Operations & Staffing Efficiency

| #   | Requirement                                          | Status | Notes |
| --- | ---------------------------------------------------- | ------ | ----- |
| 7.1 | Workload planner (staffing by event size/complexity) | ⬜     |       |
| 7.2 | Setup time prediction from historical data           | ⬜     |       |
| 7.3 | Maintenance alerts for rooms/equipment               | ⬜     |       |

---

## Rollup

| Area                  | Done   | Partial | Pending | Total  |
| --------------------- | ------ | ------- | ------- | ------ |
| 1. Agenda Generator   | 7      | 2       | 1       | 10     |
| 2. EBC Chatbot        | 2      | 1       | 2       | 5      |
| 3. Meeting Notes      | 0      | 0       | 8       | 8      |
| 4. Smart Space        | 1      | 1       | 2       | 4      |
| 5. Calendar Mgmt      | 2      | 0       | 3       | 5      |
| 6. Client Interaction | 3      | 0       | 1       | 4      |
| 7. Ops & Staffing     | 0      | 0       | 3       | 3      |
| **Total**             | **15** | **4**   | **20**  | **39** |

~38% done, ~10% partial, ~51% pending.

---

---

## 8. Infra & Performance (shipped, not client requirements)

| #   | Feature                                       | Status | Notes                                                                      |
| --- | --------------------------------------------- | ------ | -------------------------------------------------------------------------- |
| 8.1 | SSE streaming endpoint + latency waterfall UI | ✅     | `/process_query_stream` streams LLM + tool lifecycle events                |
| 8.2 | Bedrock prompt caching                        | ✅     | System prompt + tool catalog cached; cuts input token cost on repeat calls |
| 8.3 | Parallel tool dispatch                        | ✅     | ThreadPoolExecutor fires independent tool calls concurrently               |
| 8.4 | Time-token substitution                       | ✅     | `TODAY_START` etc. resolved server-side before hitting OpenSearch          |
| 8.5 | Haiku sub-LLM for email generation            | ✅     | Confirmation email body generated by Haiku, not template                   |
| 8.6 | Per-user memory system                        | 🟡     | `memory_manager.py` built; blocked on Postgres RDS setup                   |

---

## Suggested next priorities

1. **Attendee-aware presenter ranking (2.3 + 2.4)** — C-level flags + strategic-account flags already in OpenSearch. Feed into `suggest_presenters` ranking. Zero new integrations needed.

2. **Cross-event conflict detection (4.3)** — current check is per-room. Extend to catch same-presenter double-booked across events in the same date window.

3. **Memory system go-live (8.6)** — spin up Postgres RDS, run migration, set `MEMORY_DATABASE_URL` in Lambda env. Code is ready.

4. **Room recommendation ranking (4.1)** — needs data discovery on what room attributes the BriefingIQ API returns.

5. **Auto holds + confirm/release (5.4)** — needs EventBridge/cron + notification channel. Biggest scope, needs product decision.

6. **Meeting notes / section 3** — blocked on Zoom AI Companion vs. build-our-own decision.
