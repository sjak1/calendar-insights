# EBC AI Agenda Generator - Data Availability Analysis

## Overview

This document maps the required input fields for the AI-Assisted Agenda Generator against the available data in the database.

---

## Required Input Fields vs Database Availability

### ✅ **AVAILABLE DATA**

#### 1. **Customer Company Profile & Industry Vertical**

- **Status**: ✅ **AVAILABLE**
- **Source**:
  - `VW_OPERATIONS_REPORT.CUSTOMERNAME` - Customer company name
  - `VW_OPERATIONS_REPORT.CUSTOMERINDUSTRY` - Industry vertical (e.g., "Retail", "Health Care")
  - `VW_OPERATIONS_REPORT.ACCOUNTTYPE` - Account classification (e.g., "Global 500", "Lead Account")
  - `VW_OPERATIONS_REPORT.LINEOFBUSINESS` - Line of business (e.g., "LAD", "GBU - Oracle Health")
  - `t_request_agenda_details.account_name` - Account name
  - `t_request_agenda_details.industry` - Industry classification
  - `t_request_agenda_details.account_type` - Account type

**Sample Data Found:**

- Companies: HCL Technologies, HP, Lockheed Martin, Audi, AllianceIT, Salesforce, Ford Motor
- Industries: Retail, Health Care, Natural Resources, Media & Entertainment, Financial Services, Healthcare
- Account Types: Global 500, Lead Account, Current Customer, Analyst

---

#### 2. **Meeting Objectives & EBD Details**

- **Status**: ✅ **AVAILABLE** (Partial)
- **Source**:
  - `VW_OPERATIONS_REPORT.MEETINGOBJECTIVE` - Meeting objectives text
  - `t_request_agenda_details.meeting_objective` - Meeting objective field
  - `t_request_agenda_details.is_ebd_included` - Flag indicating if EBD is included (NUMBER: 0/1)

**Note**: The `is_ebd_included` field exists but the actual EBD document content/details may not be stored in the database. You may need to check if EBD content is stored in:

- Custom fields (`text_area_field_X` in `m_request_master` or `t_request_agenda_details`)
- External document storage
- Another table not yet analyzed

**Sample Data Found:**

- Meeting objectives: "HCL Technologies meeting objective", "HP meeting objective"
- EBD flag exists but sample data shows NULL values

---

#### 3. **Visit Focus**

- **Status**: ✅ **AVAILABLE**
- **Source**:
  - `VW_OPERATIONS_REPORT.VISITFOCUS` - Visit focus field
  - `t_request_agenda_details.meeting_focus` - Meeting focus
  - `t_request_agenda_details.meeting_sub_focus` - Sub-focus

**Sample Data Found:**

- Visit Focus values: "Oracle Playbook (formerly O@O)", "Hardware", "Corporate Strategy", "Analytics"

---

#### 4. **Sales Plays & Strategic Themes**

- **Status**: ✅ **AVAILABLE**
- **Source**:
  - `VW_OPERATIONS_REPORT.SALESPLAY` - Sales plays (can be single value or JSON array)
  - `VW_OPERATIONS_REPORT.PILLARS` - Strategic pillars/themes (can be single value or JSON array)

**Sample Data Found:**

- Sales Plays:
  - "Other - Siebel to CX Cloud"
  - ["Revenue Transformation","Marketing and Sales Unification"]
  - ["Revenue Transformation","Service Automation"]
- Pillars:
  - "Apps - Financial Excellence"
  - ["GIU - Retail","Apps - Customer Experience"]
  - ["Apps - Empowered Workforce","GIU - Food & Beverage"]

**Note**: These fields can contain either single string values or JSON arrays, so parsing logic will be needed.

---

#### 5. **Title Level & Mix of Attendees**

- **Status**: ✅ **AVAILABLE**
- **Source**:
  - `VW_ATTENDEE_REPORT.BUSINESSTITLE` - Job titles (e.g., "IT Business Analyst", "Senior Product Manager")
  - `VW_ATTENDEE_REPORT.CHIEFOFFICERTITLE` - C-level titles (e.g., "CRO - Chief Risk Officer", "CMO - Chief Marketing Officer", "CISO - Chief Information Security Officer", "COO - Chief Operating Officer")
  - `VW_ATTENDEE_REPORT.DECISIONMAKER` - Decision maker flag ("Yes"/"No")
  - `VW_ATTENDEE_REPORT.INFLUENCER` - Influencer flag ("Yes"/"No")
  - `VW_ATTENDEE_REPORT.ISTECHNICAL` - Technical flag ("Yes"/"No")
  - `VW_ATTENDEE_REPORT.ATTENDEETYPE` - Internal/External classification
  - `VW_ATTENDEE_REPORT.ISREMOTE` - Remote vs in-person indicator

**Sample Data Found:**

- Business Titles: IT Business Analyst, Senior Product Manager, Principal Engineer, Data Scientist, Technical Architect
- C-Level Titles: CRO, CMO, CISO, COO
- Decision Makers: Yes/No flags available
- Attendee Types: Internal, External

---

#### 6. **Previous Meetings for Same Company**

- **Status**: ✅ **AVAILABLE**
- **Source**:
  - `VW_OPERATIONS_REPORT.CUSTOMERNAME` - Can be used to group by company
  - `VW_OPERATIONS_REPORT.STARTDATEMS` - Meeting dates (epoch milliseconds)
  - `VW_OPERATIONS_REPORT.EVENTID` - Unique event identifier
  - All other fields in `VW_OPERATIONS_REPORT` for historical meeting data

**Sample Data Found:**

- Companies with multiple meetings:
  - Audi: 22 meetings (Dec 2026)
  - AllianceIT: 13 meetings (Dec 2025 - Dec 2026)
  - Salesforce: 12 meetings (Dec 2025)
  - HP: 10 meetings (Dec 2025 - Jan 2026)
  - Ford Motor: 9 meetings (Dec 2025 - Dec 2026)

**Query Pattern:**

```sql
SELECT * FROM VW_OPERATIONS_REPORT
WHERE CUSTOMERNAME = 'Company Name'
ORDER BY STARTDATEMS DESC
```

---

#### 7. **Agenda Recommendations from Similar Briefings**

- **Status**: ✅ **AVAILABLE** (Indirect)
- **Source**:
  - `t_request_agenda` - Contains agenda structure and items
    - `text_field_2` - Agenda items (e.g., "Lunch - Executive Dining Room", "Reception - Special Menu", "Break - Beverages Only")
  - `t_request_agenda_details` - Meeting details that can be used to find similar meetings
  - Can match on: Industry, Visit Focus, Sales Play, Pillars, Account Type

**Query Pattern for Similar Meetings:**

```sql
-- Find similar meetings by industry and visit focus
SELECT * FROM VW_OPERATIONS_REPORT v
JOIN t_request_agenda a ON a.request_master_id = v.EVENTID
WHERE v.CUSTOMERINDUSTRY = 'Target Industry'
  AND v.VISITFOCUS = 'Target Visit Focus'
  AND v.SALESPLAY LIKE '%Target Sales Play%'
```

---

### ⚠️ **PARTIALLY AVAILABLE / NEEDS VERIFICATION**

#### 1. **Executive Briefing Document (EBD) Content**

- **Status**: ⚠️ **PARTIAL**
- **Available**:
  - `is_ebd_included` flag exists
- **Missing/Unclear**:
  - Actual EBD document content/details
  - EBD objectives, customer context, strategic priorities
  - May be in custom fields (`text_area_field_X`) or external storage

**Recommendation**: Check if EBD content is stored in:

- `m_request_master.text_area_field_X` fields
- `t_request_agenda_details.text_area_field_X` fields
- External document management system
- Another table not yet discovered

---

#### 2. **Oracle Sales Plays (Specific Library)**

- **Status**: ⚠️ **PARTIAL**
- **Available**:
  - `SALESPLAY` field contains sales play names
- **Missing/Unclear**:
  - Structured Oracle sales play library/catalog
  - Sales play descriptions, templates, recommended agenda items
  - May need to be sourced from external Oracle sales play repository

**Recommendation**:

- If Oracle maintains a separate sales play library, it may need to be integrated
- Current `SALESPLAY` field appears to contain play names but may not have full play definitions

---

### ❌ **NOT FOUND IN DATABASE**

#### 1. **Structured Customer Insights**

- **Status**: ❌ **NOT FOUND**
- **What's Missing**:
  - Customer-specific insights, pain points, strategic initiatives
  - Customer relationship history beyond meeting count
  - Customer preferences, feedback from previous briefings
  - May be in custom fields or external CRM system

**Recommendation**:

- Check custom fields in `m_request_master` and `t_request_agenda_details`
- May need integration with CRM system (e.g., Salesforce, Oracle Sales Cloud)
- Check if there's a separate customer insights/notes table

---

#### 2. **Agenda Templates/Recommendations Library**

- **Status**: ❌ **NOT FOUND AS STRUCTURED DATA**
- **What's Available**:
  - Historical agenda items in `t_request_agenda.text_field_2`
  - Can derive recommendations from similar past meetings
- **What's Missing**:
  - Structured agenda template library
  - Pre-defined agenda item recommendations by sales play
  - Best practice agenda structures

**Recommendation**:

- Build recommendation engine based on historical agenda patterns
- May need to create a separate agenda templates/master data table

---

## Summary Table

| Requirement               | Status       | Source Table/View        | Field Name           | Notes                        |
| ------------------------- | ------------ | ------------------------ | -------------------- | ---------------------------- |
| Company Profile           | ✅ Available | VW_OPERATIONS_REPORT     | CUSTOMERNAME         |                              |
| Industry Vertical         | ✅ Available | VW_OPERATIONS_REPORT     | CUSTOMERINDUSTRY     |                              |
| Account Type              | ✅ Available | VW_OPERATIONS_REPORT     | ACCOUNTTYPE          |                              |
| Line of Business          | ✅ Available | VW_OPERATIONS_REPORT     | LINEOFBUSINESS       |                              |
| Meeting Objectives        | ✅ Available | VW_OPERATIONS_REPORT     | MEETINGOBJECTIVE     |                              |
| EBD Included Flag         | ✅ Available | t_request_agenda_details | is_ebd_included      | Flag exists                  |
| EBD Content               | ⚠️ Partial   | Unknown                  | Unknown              | May be in custom fields      |
| Visit Focus               | ✅ Available | VW_OPERATIONS_REPORT     | VISITFOCUS           |                              |
| Sales Plays               | ✅ Available | VW_OPERATIONS_REPORT     | SALESPLAY            | Can be JSON array            |
| Strategic Themes/Pillars  | ✅ Available | VW_OPERATIONS_REPORT     | PILLARS              | Can be JSON array            |
| Attendee Titles           | ✅ Available | VW_ATTENDEE_REPORT       | BUSINESSTITLE        |                              |
| C-Level Titles            | ✅ Available | VW_ATTENDEE_REPORT       | CHIEFOFFICERTITLE    |                              |
| Decision Makers           | ✅ Available | VW_ATTENDEE_REPORT       | DECISIONMAKER        |                              |
| Attendee Mix              | ✅ Available | VW_ATTENDEE_REPORT       | Multiple fields      | Type, Remote, Technical      |
| Previous Meetings         | ✅ Available | VW_OPERATIONS_REPORT     | CUSTOMERNAME + dates | Can query by company         |
| Similar Briefings         | ✅ Available | Multiple tables          | Multiple fields      | Can match on industry/focus  |
| Historical Agendas        | ✅ Available | t_request_agenda         | text_field_2         | Agenda items                 |
| Customer Insights         | ❌ Not Found | N/A                      | N/A                  | May need CRM integration     |
| Oracle Sales Play Library | ⚠️ Partial   | VW_OPERATIONS_REPORT     | SALESPLAY            | Names only, not full library |
| Agenda Templates          | ❌ Not Found | N/A                      | N/A                  | Can derive from history      |

---

## Recommendations

### 1. **Immediate Actions**

- ✅ Most core data is available - you can proceed with AI agenda generation
- ⚠️ Verify EBD content location (check custom fields or external storage)
- ⚠️ Clarify if Oracle sales play library needs to be integrated separately

### 2. **Data Enhancements Needed**

- Create/identify customer insights data source
- Build agenda template library or derive from historical patterns
- Verify EBD document content storage location

### 3. **Implementation Approach**

- Use `VW_OPERATIONS_REPORT` as primary source for meeting context
- Use `VW_ATTENDEE_REPORT` for attendee analysis
- Use `t_request_agenda` for historical agenda patterns
- Query similar meetings by matching on: Industry + Visit Focus + Sales Play + Pillars
- Parse JSON arrays in `SALESPLAY` and `PILLARS` fields

### 4. **Query Patterns for AI Agenda Generation**

```sql
-- Get meeting context
SELECT * FROM VW_OPERATIONS_REPORT WHERE EVENTID = ?

-- Get attendees
SELECT * FROM VW_ATTENDEE_REPORT WHERE EVENTID = ?

-- Find similar past meetings
SELECT * FROM VW_OPERATIONS_REPORT
WHERE CUSTOMERINDUSTRY = ?
  AND VISITFOCUS = ?
  AND SALESPLAY LIKE ?
ORDER BY STARTDATEMS DESC

-- Get historical agendas for similar meetings
SELECT a.* FROM t_request_agenda a
JOIN VW_OPERATIONS_REPORT v ON a.request_master_id = v.EVENTID
WHERE v.CUSTOMERINDUSTRY = ?
  AND v.VISITFOCUS = ?
```

---

## Conclusion

**Overall Assessment**: ✅ **~85% of required data is available**

The database contains most of the core data needed for AI agenda generation:

- ✅ Company profiles and industry data
- ✅ Meeting objectives and visit focus
- ✅ Sales plays and strategic pillars
- ✅ Attendee title levels and mix
- ✅ Previous meetings for same company
- ✅ Historical agenda items from similar briefings

**Gaps to Address**:

- ⚠️ EBD document content (flag exists, content location unclear)
- ⚠️ Full Oracle sales play library (names available, full definitions may be external)
- ❌ Structured customer insights (may need CRM integration)
- ❌ Pre-defined agenda templates (can be derived from historical data)

The system can proceed with AI agenda generation using available data, with the option to enhance later with additional data sources.
