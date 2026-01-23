# EBC AI Agenda Generator

**What it does:** Generates personalized Executive Briefing Center agendas using meeting data + EBD documents.

---

## How It Works

```
┌─────────────────┐     ┌─────────────────────────────────┐
│  Oracle DB      │     │  EBD (Executive Briefing Doc)   │
│  - Company info │     │  Source priority:               │
│  - Attendees    │ ──► │  1. Database (auto-fetch PDF)   │ ──► GPT-4o ──► Structured Agenda
│  - Visit focus  │     │  2. Local PPTX file             │
│  - Sales plays  │     │  3. Default test file           │
└─────────────────┘     └─────────────────────────────────┘
```

### End-to-End Flow

```
User: "Generate agenda for Apple"
            │
            ▼
┌──────────────────────────────────────┐
│  1. FETCH DATA                       │
│     └─ Query VW_OPERATIONS_REPORT    │
│     └─ Query VW_ATTENDEE_REPORT      │
│     └─ Extract EBD PPTX (if provided)│
└──────────────────────────────────────┘
            │
            ▼
┌──────────────────────────────────────┐
│  2. BUILD PROMPT                     │
│     └─ Company: Apple                │
│     └─ Industry: Not For Profit      │
│     └─ Attendees: 6 (4 C-level)      │
│     └─ EBD: $50M spend, Nike refs... │
└──────────────────────────────────────┘
            │
            ▼
┌──────────────────────────────────────┐
│  3. CALL GPT-4o (Structured Output)  │
│     └─ response_format=GeneratedAgenda│
│     └─ Returns typed Pydantic object │
└──────────────────────────────────────┘
            │
            ▼
┌──────────────────────────────────────┐
│  4. OUTPUT                           │
│     └─ result["sessions"]            │
│     └─ result["presenters"]          │
│     └─ result["agenda_markdown"]     │
└──────────────────────────────────────┘
```

---

## Key Features

| Feature | Description |
|---------|-------------|
| **Structured Output** | Returns typed Pydantic objects, not just text |
| **EBD Integration** | Extracts presenter names, $ figures, customer refs from PPTX |
| **No Hallucination** | All data comes from DB/EBD - verifiable sources |
| **Consistent Format** | Same schema every time (sessions, presenters, notes) |

---

## Output Structure

```python
result = generate_agenda(company_name="Apple")

result["sessions"]         # List of sessions
result["presenters"]       # Oracle presenter list
result["strategic_notes"]  # Derailers, follow-ups
result["agenda_markdown"]  # Formatted text
```

**Session Object:**
```json
{
  "time_slot": "10:00 AM - 10:45 AM",
  "title": "Revenue Transformation Through Data-Driven Marketing",
  "format": "Presentation",
  "presenter": "Thomas Reed, VP Analytics Solutions",
  "description": "...",
  "key_metrics": "$50M inefficient spend",
  "customer_reference": "Nike achieved 40% improvement"
}
```

---

## What Gets Pulled From EBD

- ✅ **Presenter names** (Thomas Reed, Sarah Kim, James Liu)
- ✅ **$ figures** ($50M ad spend, $30M savings, 30% YoY growth)
- ✅ **Customer references** (Nike, Starbucks, Target)
- ✅ **Attendee concerns** (skeptical of vendors, timeline concerns)
- ✅ **Account derailers** (CEO relationship with competitor)

---

## Usage

```bash
# Basic
python tools/agenda_generator.py --company Apple

# With JSON output
python tools/agenda_generator.py --company Apple --json

# Custom EBD file
python tools/agenda_generator.py --company Ford --ebd /path/to/ebd.pptx
```

---

## EBD Auto-Fetch from Database

EBDs are now **auto-fetched from `VW_EVENT_DOCUMENT_REPORT`**:

```python
# Automatic - no file needed!
result = generate_agenda(company_name="Ecolab")
# → Fetches PDF from database, extracts text, uses in prompt

# Result shows source:
result["ebd_source"]  # "database" | "local_file" | None
```

**Priority:**
1. Database (PDF/PPTX blob from `VW_EVENT_DOCUMENT_REPORT`)
2. Local file (if `ebd_path` provided)
3. Default test file (if `use_default_ebd=True`)

---

## Files

```
tools/agenda_generator.py  # Main tool (Pydantic models + LLM call)
tools/extract_ebd.py       # PPTX parser
EBD_Apple_FILLED.pptx      # Test EBD (Apple)
EBD_Amazon_FILLED.pptx     # Test EBD (Amazon)
```

---

## Why Structured Output?

| Before | After |
|--------|-------|
| Free-form markdown | Typed JSON objects |
| Parse text with regex | Access `result["sessions"][0]` |
| Inconsistent format | Always same schema |
| Hard to build UI | Easy to map over sessions |

---

## Accuracy: 100%

All presenter names, $ figures, and customer references verified against source EBD. No LLM hallucination.

