# Project Requirements: AI Assistant for BriefingIQ

This document tells you _what_ to build
and _what data you have to work with_. Every implementation choice - language,
framework, file layout, function names, API shape, prompting strategy, agent
loop design - is yours.

---

## 1. What BriefingIQ is

BriefingIQ is an enterprise platform for managing **executive briefings** and
customer-meeting **events** - the kind of multi-hour or multi-day visits a
large company runs when an important customer comes to one of their briefing
centers.

A briefing center is a physical place (or virtual room) with bookable rooms,
catering staff, and a roster of internal experts. An event coordinator's job
is to:

- Take a request for a customer visit ("Acme wants to meet our cloud team next
  Friday in Redwood Shores").
- Build an agenda of **sessions** around the customer's interests.
- Assign **rooms** to each session, avoiding conflicts.
- Find the right internal **presenters** for each topic.
- Coordinate **catering** and AV.
- Send the customer a confirmation, and the internal team an ops sheet.

Today they do this by clicking through forms and spreadsheets. **Your job is
to build a natural-language AI assistant that lets them do it by chatting.**

### Domain vocabulary

| Term                   | Meaning                                                                                                                                                            |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Event**              | One customer visit / briefing. Has a customer, a date range, a location, attendees, an opportunity (revenue), a status.                                            |
| **Category**           | A grouping of events (e.g. "Customer Briefing Request - Redwood", "Executive Dining Request").                                                                     |
| **Activity / Session** | One scheduled block within an event - a topic presentation, a catering slot, an executive meeting. Has a start/end time, a room, optionally a topic and presenter. |
| **Resource / Room**    | A bookable physical or virtual room with a capacity.                                                                                                               |
| **Topic**              | The subject of a session (e.g. "Cybersecurity for Financial Services").                                                                                            |
| **Presenter**          | An internal expert who delivers a topic in a session.                                                                                                              |
| **External attendees** | Customer-side people coming to the event.                                                                                                                          |
| **Internal attendees** | Host-side people running the event.                                                                                                                                |
| **Tenant / Customer**  | A company that uses BriefingIQ. Strict isolation between tenants.                                                                                                  |

---

## 2. Goal

Build **one HTTP endpoint** that fronts an LLM agent with **tools**. The user
sends a natural-language message + context (who they are, what they're
viewing); the agent picks the right tool(s), runs them, and replies.

The tools you need to give it:

- **Query OpenSearch** - answer anything about events/activities (see §3).
- **List rooms / read room calendar / find vacant slots / book a room** —
  via the BriefingIQ REST API, with a conflict check on writes.
- **Suggest presenters** - ranked from historical activities.
- **Generate an agenda** and push it back to BriefingIQ as activities.
- **Draft a confirmation email** to the customer.
- **Draft an internal catering / ops sheet.**
- **Render results as charts, tables, or PDFs.**

Add more tools if you need them. Skip the ones that aren't needed for a turn.

---

## 3. What data you have to work with

You have three data sources. Treat them as given - you do not build them, you
read from / write to them.

### 3.1 OpenSearch - `events` index

One document per event. Covers event-level info: customer, industry, status,
category, location, attendees, opportunity/revenue, host, visit summary,
catering, etc. Deeply nested under paths like `eventData.VISIT_INFO.data.*`.
Full field mapping will be shared separately.

### 3.2 OpenSearch - `activities` index

One document per session/activity (~2k+ docs). Links to its parent event by
`eventId`. Covers topic, presenter, room, catering, and per-activity status.
Use this for per-session questions (topic counts, presenter history, room
utilization).

**Query rules (both indices):** use `.keyword` subfields for filters / sort /
aggregations; date ranges go against epoch-ms fields with
`format: "epoch_millis"`; fields are plain objects/arrays (no nested
queries).

### 3.3 BriefingIQ REST API

A separate service exposes live, writable operational data. You'll get a
sandbox tenant + an auth token in the request headers. Key capabilities:

- **List rooms** for a tenant or for a specific event.
- **Read a room's calendar** - existing bookings/blocks on a resource.
- **Write a calendar entry** - block/reserve a room for a window (the API
  accepts a `BLOCKED`/`BOOKED` type plus comments).
- **Create activities** on an event - title, time slot, optional room,
  optional topic, optional presenter.
- **Assign presenters** to activities.
- **Read event metadata** that the search index might be stale on.

You don't get to redesign this API. You consume it. (Endpoint list and auth
flow will be provided separately.)

**Connecting to OpenSearch:**

- Cluster URL via env var `OPENSEARCH_URL`
  (e.g. `https://vpc-xxxx.us-west-2.es.amazonaws.com`).
- Basic auth via `OPENSEARCH_USERNAME` / `OPENSEARCH_PASSWORD`.
- `OPENSEARCH_VERIFY_CERTS=false` for the sandbox (self-signed).
- Use the official `opensearch-py` client (or equivalent). Sandbox
  credentials provided separately - never commit them.

---

## 4. What the AI assistant must be able to do

These are _capabilities_, not function specs. Implement them however you like.

### 4.1 Answer questions

Anything answerable from the events / activities indices. Examples the user
might ask:

- "How many briefings this quarter?"
- "List the events for the Acme account."
- "Which industries had the most C-level attendees last year?"
- "Show me revenue by region for closed-won opportunities."
- "Who presented on Cybersecurity in the last 6 months?"
- "What was the meeting objective for the Jaguar visit last March?"

The assistant must be able to write its own search queries (DSL) against
OpenSearch, including aggregations for "how many" / "group by" questions.

### 4.2 Show results visually

When the question implies a chart or a table, return one. Pie/bar/line/
column/area/heatmap/timeline at minimum. Return a structured config the
frontend renders; you choose the shape (Highcharts-compatible is one option).

Same for tables - return a structured list of columns + rows.

### 4.3 Find and book rooms

Multi-turn capability:

- List rooms relevant to the current event or tenant.
- Show what's already booked on a given room.
- Find free windows of a given duration on a date, honoring working hours
  (default 9 am – 6 pm in the user's timezone).
- Reserve a window on a room - **with a conflict check first**. If something
  already overlaps, refuse and report the conflict; do not write.

### 4.4 Suggest presenters

Given a topic / industry / customer / event, rank the best presenters using
the historical `activities` data - past appearances, audience seniority match
(C-level / VP+ / senior), recency. Optionally check availability for a given
time window and flag conflicts per presenter.

### 4.5 Generate agendas

Given an event (or just a company name), produce a draft agenda - a list of
sessions with titles, time slots, and suggested presenters. Use past similar
briefings as context. Let the user review, then on confirmation push the
sessions into BriefingIQ as activities.

### 4.6 Draft documents

- **Customer confirmation email** - fetches the event's live details and
  produces a ready-to-send subject + body. Tone and structure should be
  generated, not template-stamped.
- **Internal catering / ops sheet** - sessions grouped by room with catering
  and AV needs.
- **PDF export** of any of the above when asked.

### 4.7 Remember context

- **Within a conversation:** follow-ups like "and the day after?" or "make it
  3 hours instead" must resolve correctly against the previous turn.
- **Across conversations:** extract and store durable user preferences;
  retrieve relevant ones automatically on each new query.

### 4.8 Tenant isolation

Every query and every write must be scoped to the calling user's tenant. A
user from tenant A must never see or affect tenant B's data, no matter what
they type.

---

## 5. Input / output contract (user-facing)

You design the HTTP shape. The only hard requirements are:

**Input from the UI must convey:**

- The user's natural-language message.
- A conversation/session identifier (so multi-turn works).
- Context the UI already knows: who the user is (email), which tenant they
  belong to, which event or category they're currently viewing (may be
  absent), and their timezone. Pass this however you like - headers, body
  fields, whatever.

**Output back to the UI must convey, depending on the request:**

- A written natural-language reply.
- (Optional) Structured data for the UI to render: a chart config, a table,
  a downloadable file reference (PDF), an email draft (subject + body), an
  agenda preview, etc.
- The session id so the client can keep chatting.
- Useful confirmation when the assistant performed a write (e.g. "booked
  Horizon Chamber for Friday 2–4 pm").

**Bonus:** offer a streaming variant so the UI can show progress while a long
query runs (e.g. "searching events… checking room availability… drafting
email…"). How you stream is your call - SSE, websockets, chunked HTTP - pick
one and justify it.

---

## 6. Example end-to-end scenarios

You should be able to demo all of these against the sandbox tenant.

**Scenario A - counting**

> User: "How many confirmed briefings did we run for the Healthcare industry
> last quarter?"
>
> Expect: a single number plus a one-line breakdown.

**Scenario B - table**

> User: "Show me a table of all events for Acme with their status, location,
> and opportunity revenue."
>
> Expect: a 4-column table.

**Scenario C - chart**

> User: "Chart briefings by region for this year."
>
> Expect: a bar/column chart config.

**Scenario D - room booking (multi-turn)**

> User: "Find me a 90-minute slot tomorrow afternoon in any room."
> → assistant lists candidates.
> User: "Book the Horizon one at 2 pm."
> → assistant runs conflict check, then either books or reports a conflict.

**Scenario E - agenda + push**

> User: "Generate an agenda for the Jaguar visit next week."
> → assistant proposes sessions with topics, times, presenters.
> User: "Looks good, add it to the event."
> → assistant writes the activities to BriefingIQ.

**Scenario F - drafting**

> User: "Draft a confirmation email for the Acme briefing."
>
> Expect: subject + body using live event details, tone appropriate.

**Scenario G - presenter suggestion with availability**

> User: "Who's our best presenter for cybersecurity to a C-level audience on
> Friday 10 am – 11 am?"
>
> Expect: ranked list, each marked available / conflicted.

**Scenario H - memory**

> User (Monday): "I prefer the Horizon room for executive briefings."
> User (Wednesday): "Find me a room for next week's executive briefing."
> → assistant proactively suggests Horizon first.

---

## 7. Constraints

- **Language / runtime:** any modern backend stack you can defend. Python
  3.12 is what the existing system uses; you may match it or pick otherwise.
- **LLM provider:** must support tool/function calling. AWS Bedrock (Claude
  family) and OpenAI both qualify. Make the choice swappable.
- **Search:** OpenSearch (don't reimplement; it already holds the data).
- **Postgres** for your own state.
- **Deployment:** must run locally for development and as a deployable
  container in the cloud. Lambda-compatible is a plus.
- **Latency target:** read-only queries with no tool use should feel
  conversational (a couple of seconds). Multi-tool queries can take longer
  but should stream progress.

---

## 8. Out of scope

- The frontend chat UI.
- Authentication / SSO - assume a gateway upstream has authenticated the user
  and passes their identity to you.
- The BriefingIQ REST API itself, and the OpenSearch indexes - both exist
  already, you read from / write to them.
- Building the data pipeline that populates OpenSearch.
