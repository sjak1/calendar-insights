# Client Requirements — Status Tracker

Tracking what's built vs pending across all the EBC AI requirements.

Legend: ✅ done | 🟡 partial | ⬜ not started

---

## 1. AI-Assisted Agenda Generator (external + internal)

| # | Requirement | Status | Notes |
|---|------------|--------|-------|
| 1.1 | Auto-generate agenda from EBC request | ✅ | `generate_agenda` tool, Bedrock Sonnet |
| 1.2 | Use customer company profile | ✅ | Pulled from `eventData.VISIT_INFO.data.customerName` |
| 1.3 | Use industry vertical | ✅ | Pulled from `customerIndustry` |
| 1.4 | Use EBD (Executive Briefing Document) | 🟡 | EBD fetched from DB, PDF parse needs `pdfplumber` (not installed on Lambda) |
| 1.5 | Use meeting objectives / visit focus | ✅ | Passed into agenda prompt |
| 1.6 | Use marketing/sales plays & strategic themes | ⬜ | No sales plays data source wired in |
| 1.7 | Use attendee title level & mix | ✅ | C-level, decision makers, remote counts surfaced |
| 1.8 | Pull agenda recommendations from similar briefings | ✅ | `similar_briefings` query on past events |
| 1.9 | EBC Manager review/refine flow | 🟡 | Generated agenda is editable, but no dedicated review UI |
| 1.10 | Push final agenda back to BriefingIQ | ✅ | `push_agenda_to_briefingiq` + `get_event_rooms` |

---

## 2. EBC Chatbot within EIQ (Ask Oracle)

| # | Requirement | Status | Notes |
|---|------------|--------|-------|
| 2.1 | Find presenters by topic | ✅ | `suggest_presenters` with topic filter |
| 2.2 | Parent topic / sub-focus topic matching | 🟡 | Only topic name matched, no hierarchy parsing |
| 2.3 | Match speaker to audience level (C-suite) | ⬜ | Attendee C-level detected, not fed into presenter ranking |
| 2.4 | Strategic account awareness | ⬜ | No strategic-account flag in ranking |
| 2.5 | Chatbot inside EIQ app | ✅ | Whole system runs embedded in BriefingIQ |

---

## 3. EBC AI Meeting Notes & Action Item Generator

| # | Requirement | Status | Notes |
|---|------------|--------|-------|
| 3.1 | Live/recorded meeting transcription | ⬜ | Zoom AI Companion suggested in spec |
| 3.2 | Key discussion summary | ⬜ | |
| 3.3 | Action items with owner attribution | ⬜ | |
| 3.4 | Decision logs | ⬜ | |
| 3.5 | Follow-up recommendations | ⬜ | Discussed as a feature idea, not built |
| 3.6 | Post-meeting follow-up email draft | ⬜ | Scoped out, not implemented |
| 3.7 | Distribute to Sales/EBC/leadership | ⬜ | |
| 3.8 | Integration with BIQ | ⬜ | |

---

## 4. OCC — Smart Space & Resource Optimization

| # | Requirement | Status | Notes |
|---|------------|--------|-------|
| 4.1 | Recommend best rooms by size/setup/AV/catering | ⬜ | `list_rooms` returns rooms (event-aware) but no AI ranking on capacity/AV/catering |
| 4.2 | Predictive availability (peak times, booking windows) | ⬜ | |
| 4.3 | Conflict detection — overlapping events/double-booked resources | 🟡 | Agenda push pre-flights per-room conflicts via `get_resource_schedule` (merges activities + blocks). Cross-event / cross-room detection still pending. |
| 4.4 | Presenter double-booking check | ✅ | `_check_presenter_conflicts` in `tools/presenter_suggest.py`; overlap query on activities index; `available` + `conflicts` stamped on every suggestion; wired into `agenda_generator` with event-day window |

---

## 5. OCC — Automated Calendar Management

| # | Requirement | Status | Notes |
|---|------------|--------|-------|
| 5.1 | Natural language booking | ✅ | `block_calendar` with conflict pre-flight; LLM maps NL → ISO in request timezone |
| 5.2 | Vacant timeslot finder | ✅ | `find_vacant_slots` computes free windows; `list_event_activities` surfaces what's already on |
| 5.3 | Outlook / Google calendar sync | ⬜ | |
| 5.4 | Auto holds + confirm/release reminders | ⬜ | `block_calendar` creates holds; no scheduler or reminder channel wired |
| 5.5 | Dynamic rescheduling when events move | ⬜ | |

---

## 6. OCC — Client Interaction & Booking Assistance

| # | Requirement | Status | Notes |
|---|------------|--------|-------|
| 6.1 | 24/7 booking inquiry chatbot | 🟡 | Chat inside BIQ handles queries, not a public-facing bot |
| 6.2 | Auto-draft event confirmations | ⬜ | |
| 6.3 | Auto-draft catering/setup sheets | ⬜ | |
| 6.4 | Follow-up nudges for pending holds | ⬜ | |

---

## 7. OCC — Operations & Staffing Efficiency

| # | Requirement | Status | Notes |
|---|------------|--------|-------|
| 7.1 | Workload planner (staffing by event size/complexity) | ⬜ | |
| 7.2 | Setup time prediction from historical data | ⬜ | |
| 7.3 | Maintenance alerts for rooms/equipment | ⬜ | |

---

## Rollup

| Area | Done | Partial | Pending | Total |
|------|------|---------|---------|-------|
| 1. Agenda Generator | 6 | 3 | 1 | 10 |
| 2. EBC Chatbot | 2 | 1 | 2 | 5 |
| 3. Meeting Notes | 0 | 0 | 8 | 8 |
| 4. Smart Space | 1 | 1 | 2 | 4 |
| 5. Calendar Mgmt | 2 | 0 | 3 | 5 |
| 6. Client Interaction | 0 | 1 | 3 | 4 |
| 7. Ops & Staffing | 0 | 0 | 3 | 3 |
| **Total** | **11** | **6** | **22** | **39** |

~28% done, ~15% partial, ~56% pending.

---

## Suggested next priorities

Ranked by **impact × feasibility** — first three chain directly off plumbing we already shipped, so they're cheap wins.

1. **Presenter double-booking check (4.4)** — `list_event_activities` already returns every activity across rooms with presenter data reachable per activity. Add a presenter filter + call from `suggest_presenters` to skip anyone already booked in the window. *Why first: smallest effort, builds on code from this session.*

2. **Attendee-aware presenter ranking (2.3 + 2.4)** — C-level flags + strategic-account flags are already indexed in OpenSearch and surfaced in attendee context. Just need to feed them into `suggest_presenters` ranking signals. *Why second: closes two ⬜ items with zero new integrations; attendee data is ready.*

3. **Cross-event conflict detection (4.3 → ✅)** — current conflict check is per-room during agenda push. Extend to detect same-presenter-double-booked and same-room-across-events by iterating events in the date window. *Why third: natural extension of 4.4, finishes section 4.3.*

4. **Room recommendation ranking (4.1)** — rank rooms by capacity / AV gear / catering support. Need to first audit what attributes live on `/resourcetypes/.../resources` — might need stakeholder input. *Why fourth: requires data discovery, not just code.*

5. **Auto holds + confirm/release (5.4)** — `block_calendar` already creates holds; gap is infra: EventBridge/cron scanner + email/notification channel + status transitions. *Why fifth: biggest scope in section 5 but needs product + infra decisions.*

6. **Sales plays data source (1.6)** — blocked on stakeholder input on where sales plays live.

7. **Meeting notes / follow-up email (section 3)** — entire unbuilt area (8 items), blocked on Zoom AI Companion vs. build-our-own decision. Defer until scoped.
