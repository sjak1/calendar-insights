# Agenda Generation Flow: Input to Output

Complete flow diagram showing how a user query becomes a structured agenda.

---

## 🎯 User Query

```
User: "can you generate agenda for amazon ?"
```

---

## 📊 Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          USER QUERY                                          │
│                    "generate agenda for amazon"                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ITERATION 1: LLM Tool Selection                           │
│  ─────────────────────────────────────────────────────                     │
│  Input to API:                                                              │
│    [                                                                         │
│      {"role": "user", "content": "hello"},                                  │
│      {"role": "assistant", "content": "Hello! How can I assist you?"},     │
│      {"role": "user", "content": "can you generate agenda for amazon ?"}    │
│    ]                                                                         │
│                                                                              │
│  LLM Analysis:                                                              │
│    → Recognizes "generate agenda" intent                                    │
│    → Identifies company: "amazon"                                          │
│    → Selects tool: generate_agenda                                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    LLM Function Call                                         │
│  ─────────────────────────────────────                                     │
│  {                                                                           │
│    "name": "generate_agenda",                                               │
│    "arguments": {                                                           │
│      "event_id": "",                                                        │
│      "company_name": "Amazon"                                                │
│    }                                                                         │
│  }                                                                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│              STEP 1: Fetch Meeting Context from Database                     │
│  ────────────────────────────────────────────────────────                   │
│                                                                              │
│  Query VW_OPERATIONS_REPORT:                                                │
│    → Company: Amazon                                                         │
│    → Industry: Government                                                    │
│    → Visit Focus: Internet of Things                                         │
│    → Sales Plays, Pillars, Meeting Objective                                │
│    → Event ID: 731318059148                                                  │
│                                                                              │
│  Query VW_ATTENDEE_REPORT:                                                   │
│    → 10 attendees                                                           │
│    → 5 C-level executives                                                   │
│    → 2 decision makers                                                      │
│    → 4 technical attendees                                                   │
│    → 4 remote participants                                                  │
│                                                                              │
│  Query Previous Meetings:                                                    │
│    → 0 previous meetings                                                    │
│                                                                              │
│  Query Similar Briefings:                                                    │
│    → 0 similar briefings                                                    │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│              STEP 2: Fetch EBD from Database                                │
│  ───────────────────────────────────────────                                 │
│                                                                              │
│  Query VW_EVENT_DOCUMENT_REPORT:                                            │
│    WHERE eventid = '731318059148'                                            │
│    AND document_category = 'Executive Briefing Document'                    │
│                                                                              │
│  Found:                                                                      │
│    → File: EBD_Amazon_FILLED.pptx                                            │
│    → Size: 210,723 bytes                                                    │
│    → Type: application/vnd.openxmlformats-officedocument...                 │
│                                                                              │
│  Process:                                                                    │
│    1. Download blob from database                                            │
│    2. Save to temporary file                                                │
│    3. Extract text using extract_pptx_content()                             │
│    4. Format using format_extracted_content()                               │
│    5. Result: 15,275 characters extracted                                    │
│    6. Delete temporary file                                                 │
│                                                                              │
│  EBD Content Extracted:                                                     │
│    • Business challenges ($ figures)                                         │
│    • Oracle presenter names (Thomas Reed, Sarah Kim, James Liu)              │
│    • Customer references (Honeywell, Textron, Spirit AeroSystems)          │
│    • Attendee concerns                                                       │
│    • Account derailers                                                       │
│    • Oracle talking points                                                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│              STEP 3: Build LLM Prompt                                       │
│  ───────────────────────────────                                           │
│                                                                              │
│  Prompt Components:                                                          │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────┐            │
│  │ MEETING CONTEXT                                             │            │
│  │ • Company: Amazon                                           │            │
│  │ • Industry: Government                                      │            │
│  │ • Visit Focus: Internet of Things                           │            │
│  │ • Sales Plays, Pillars, Objectives                          │            │
│  └────────────────────────────────────────────────────────────┘            │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────┐            │
│  │ ATTENDEE MIX                                                │            │
│  │ • Total: 10                                                 │            │
│  │ • C-Level: 5                                               │            │
│  │ • Decision Makers: 2                                        │            │
│  │ • Technical: 4                                              │            │
│  │ • Remote: 4                                                  │            │
│  └────────────────────────────────────────────────────────────┘            │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────┐            │
│  │ EBD CONTENT (15,275 chars)                                  │            │
│  │ • Business challenges with $ figures                         │            │
│  │ • Presenter names                                           │            │
│  │ • Customer references                                       │            │
│  │ • Attendee concerns                                         │            │
│  │ • Talking points                                            │            │
│  └────────────────────────────────────────────────────────────┘            │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────┐            │
│  │ REQUIREMENTS                                                │            │
│  │ • 6-10 sessions (10 AM - 5 PM)                             │            │
│  │ • Include lunch break                                       │            │
│  │ • Use real presenter names from EBD                        │            │
│  │ • Include $ figures in key_metrics                         │            │
│  │ • Name customer references                                 │            │
│  └────────────────────────────────────────────────────────────┘            │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│              STEP 4: LLM Processing (Structured Output)                   │
│  ────────────────────────────────────────────────────────                 │
│                                                                              │
│  API Call:                                                                   │
│    client.beta.chat.completions.parse(                                       │
│      model="gpt-4o-mini",                                                    │
│      response_format=GeneratedAgenda,  ← Pydantic schema                    │
│      temperature=0.7                                                         │
│    )                                                                         │
│                                                                              │
│  Processing Time: ~20 seconds                                                │
│                                                                              │
│  LLM Output:                                                                 │
│    → Structured Pydantic object (GeneratedAgenda)                            │
│    → 9 sessions created                                                      │
│    → Real presenter names used                                               │
│    → $ figures included in key_metrics                                      │
│    → Customer references named                                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│              STEP 5: Tool Response                                           │
│  ───────────────────────────────                                           │
│                                                                              │
│  Return Value:                                                               │
│  {                                                                           │
│    "success": true,                                                          │
│    "company": "Amazon",                                                      │
│    "industry": "Government",                                                 │
│    "visit_focus": "Internet of Things",                                      │
│    "attendee_count": 10,                                                     │
│    "ebd_used": true,                                                         │
│    "ebd_source": "database",  ← Shows EBD came from DB                      │
│    "session_count": 9,                                                      │
│    "agenda_structured": {                                                    │
│      "company": "Amazon",                                                   │
│      "oracle_presenters": [                                                  │
│        {"name": "Thomas Reed", "title": "VP Analytics Solutions"},         │
│        {"name": "Sarah Kim", "title": "Sr. Director Customer Experience"},  │
│        {"name": "James Liu", "title": "Principal Data Architect"}           │
│      ],                                                                      │
│      "sessions": [                                                          │
│        {                                                                     │
│          "time_slot": "10:00 AM - 10:30 AM",                                │
│          "title": "Welcome and Overview",                                   │
│          "presenter": "Thomas Reed",                                         │
│          "key_metrics": "$3M+ in annual savings...",                        │
│          "customer_reference": "Honeywell Aerospace..."                      │
│        },                                                                    │
│        ... (8 more sessions)                                               │
│      ]                                                                       │
│    },                                                                        │
│    "agenda_markdown": "# Executive Briefing Agenda..."                      │
│  }                                                                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│              ITERATION 2: LLM Formats Final Response                       │
│  ────────────────────────────────────────────────────────                   │
│                                                                              │
│  Input to API:                                                               │
│    [Previous conversation + function_call_output]                            │
│                                                                              │
│  LLM Processing:                                                            │
│    → Receives structured agenda data                                        │
│    → Formats into markdown for user                                         │
│    → Adds context and explanations                                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    FINAL OUTPUT TO USER                                      │
│  ──────────────────────────────────────                                     │
│                                                                              │
│  ## Executive Briefing Agenda for Amazon                                    │
│                                                                              │
│  **Company:** Amazon                                                         │
│  **Industry:** Government                                                    │
│  **Date/Time:** February 10, 2026 | 10:00 AM - 5:00 PM PST                │
│                                                                              │
│  ### Oracle Presenters                                                       │
│  - Thomas Reed, VP Analytics Solutions                                       │
│  - Sarah Kim, Sr. Director Customer Experience                            │
│  - James Liu, Principal Data Architect                                      │
│                                                                              │
│  ### Agenda Sessions                                                         │
│                                                                              │
│  **10:00 AM - 10:30 AM**                                                    │
│  **Title:** Welcome and Overview                                             │
│  **Presenter:** Thomas Reed                                                  │
│  **Key Metrics:** $3M+ in annual savings...                                │
│  **Customer Reference:** Honeywell Aerospace...                              │
│                                                                              │
│  ... (9 sessions total)                                                      │
│                                                                              │
│  ### Strategic Notes                                                         │
│  - Derailer handling                                                         │
│  - Attendee considerations                                                   │
│  - Follow-up actions                                                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 📋 Key Data Transformations

### Input → Processing → Output

| Stage | Input | Processing | Output |
|-------|-------|------------|--------|
| **1. User Query** | `"generate agenda for amazon"` | LLM intent recognition | Tool call: `generate_agenda(company_name="Amazon")` |
| **2. Database Query** | Company name | SQL queries to Oracle DB | Meeting context (10 attendees, IoT focus, etc.) |
| **3. EBD Extraction** | Event ID: `731318059148` | Query DB → Download blob → Extract PPTX | 15,275 chars of EBD text |
| **4. Prompt Building** | Meeting context + EBD text | Combine into structured prompt | 50K+ char prompt with all context |
| **5. LLM Generation** | Structured prompt | GPT-4o-mini with Pydantic schema | `GeneratedAgenda` object (typed) |
| **6. Formatting** | Structured agenda | Convert to markdown | User-friendly markdown agenda |

---

## 🔄 Data Flow Summary

```
User Query
    │
    ├─→ LLM Tool Selection
    │       │
    │       └─→ generate_agenda(company_name="Amazon")
    │               │
    │               ├─→ Database Queries
    │               │   ├─→ Meeting Details (VW_OPERATIONS_REPORT)
    │               │   ├─→ Attendees (VW_ATTENDEE_REPORT)
    │               │   └─→ Previous Meetings
    │               │
    │               ├─→ EBD Extraction
    │               │   ├─→ Query VW_EVENT_DOCUMENT_REPORT
    │               │   ├─→ Download blob (210KB PPTX)
    │               │   ├─→ Save to temp file
    │               │   ├─→ extract_pptx_content()
    │               │   ├─→ format_extracted_content()
    │               │   └─→ 15,275 chars extracted
    │               │
    │               └─→ LLM Processing
    │                   ├─→ Build prompt (context + EBD)
    │                   ├─→ Call GPT-4o-mini with Pydantic schema
    │                   └─→ Return GeneratedAgenda object
    │
    └─→ Final Response
            │
            └─→ Formatted markdown agenda
```

---

## ⏱️ Timing Breakdown

From the logs:

| Step | Duration | What Happens |
|------|----------|--------------|
| **Tool Selection** | ~2s | LLM analyzes query, selects tool |
| **DB Queries** | ~4s | Fetch meeting context (4 queries) |
| **EBD Extraction** | ~2s | Download blob, extract PPTX text |
| **LLM Generation** | ~20s | GPT-4o-mini processes prompt, generates agenda |
| **Formatting** | ~15s | LLM formats structured output to markdown |
| **Total** | ~43s | End-to-end agenda generation |

---

## 🎯 Key Features

1. **Automatic EBD Fetching**: No manual file upload needed - fetches from database
2. **Structured Output**: Uses Pydantic models for type safety
3. **Rich Context**: Combines DB data + EBD content for personalized agendas
4. **Real Data**: Uses actual presenter names, $ figures, customer references from EBD
5. **Two-Step LLM**: First generates structured data, then formats for user

---

## 📊 Output Statistics

- **Sessions Generated**: 9
- **Presenters**: 3 (from EBD)
- **EBD Content Used**: 15,275 characters
- **Final Response**: 5,174 characters (formatted markdown)
- **EBD Source**: `"database"` ✅

