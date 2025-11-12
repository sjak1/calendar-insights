# Q&A System Test Questions

## Purpose
Test the calendar insights Q&A system to validate SQL generation, CLOUD_DATE handling, table joins, and edge cases.

---

## Category 1: Basic Queries (Simple SELECT)

### 1.1 Simple Host Lookup
**Question:** Show me all meetings hosted by Mark Ashby

**Expected:** Should query `t_request_agenda_details` with exact name match

---

### 1.2 Industry Filter
**Question:** List all meetings in the Automotive industry

**Expected:** Should filter `t_request_agenda_details` by industry

---

### 1.3 Event Name Search
**Question:** Find events related to "CloudWorld"

**Expected:** Should use LIKE pattern on `m_request_master.event_name`

---

## Category 2: Date Queries (CLOUD_DATE Handling)

### 2.1 Date Range Query
**Question:** Show me all events in 2024

**Expected:** Should use `m_request_master` with proper date filtering (end_date or handle CLOUD_DATE properly)

---

### 2.2 Upcoming Events
**Question:** What events are happening in December 2025?

**Expected:** Should filter by date range, handle CLOUD_DATE columns correctly

---

### 2.3 Past Events
**Question:** Show me events that happened in November 2022

**Expected:** Should filter historical data with proper date handling

---

## Category 3: JOIN Queries (Cross-Table)

### 3.1 Host with Dates (CRITICAL TEST)
**Question:** Show meetings hosted by Surya Yadavalli with their dates

**Expected:** Should JOIN `t_request_agenda_details` to `m_request_master` via `REQUEST_MASTER_ID` to get dates. This was the original failing query!

---

### 3.2 Events with Revenue
**Question:** Show me events that have associated sales opportunities with revenue data

**Expected:** Should JOIN `m_request_master` → `t_request_opportunity` and filter for non-null revenue

---

### 3.3 Presenter Details
**Question:** List all presenters for the "Mobile World Congress 2024" event

**Expected:** Should JOIN `m_request_master` → `t_request_agenda_presenter`

---

## Category 4: Custom Field Searches (LIKE Patterns)

### 4.1 Job Title Search
**Question:** Show me all presenters who are CIOs

**Expected:** Should use `LIKE '%CIO%'` on `t_request_agenda_presenter.text_field_3`

---

### 4.2 Multiple Job Titles
**Question:** Find presenters who are either CIO, CISO, or COO

**Expected:** Should use multiple LIKE patterns with OR conditions

---

### 4.3 Dietary Restrictions
**Question:** Show me meetings with Halal dietary requirements

**Expected:** Should use `LIKE '%Halal%'` on `t_request_agenda_details.text_field_3`

---

### 4.4 Multiple Dietary Restrictions
**Question:** Find meetings with Vegan or Kosher dietary requirements

**Expected:** Should use multiple LIKE patterns

---

## Category 5: Aggregations & Analytics

### 5.1 Count by Industry
**Question:** How many meetings were held in each industry?

**Expected:** Should GROUP BY industry with COUNT

---

### 5.2 Average Attendees
**Question:** What's the average number of attendees per meeting?

**Expected:** Should use AVG on `number_of_attendees`

---

### 5.3 Total Revenue
**Question:** What's the total revenue from all opportunities?

**Expected:** Should SUM `opportunity_revenue` from `t_request_opportunity`

---

### 5.4 Events by Format
**Question:** How many events are In-Person vs Virtual vs Hybrid?

**Expected:** Should GROUP BY `event_format` in `m_request_master`

---

## Category 6: Complex Filters

### 6.1 C-Level Attendees
**Question:** Show me meetings with C-level attendees in the Automotive industry

**Expected:** Should filter by `is_c_level_attendee = 1` AND industry

---

### 6.2 Large Meetings
**Question:** Find meetings with more than 20 attendees

**Expected:** Should filter `number_of_attendees > 20`

---

### 6.3 Region Filter
**Question:** Show me all meetings in the EMEA region

**Expected:** Should filter by region in `t_request_agenda_details`

---

### 6.4 Hybrid Meetings
**Question:** List all hybrid meetings

**Expected:** Should filter by `is_hybrid` flag

---

## Category 7: Edge Cases & Limits

### 7.1 NULL Handling
**Question:** Show me meetings where the meeting focus is not specified

**Expected:** Should handle NULL checks properly

---

### 7.2 Empty Results
**Question:** Show me meetings hosted by "NonExistentPerson XYZ"

**Expected:** Should return empty result gracefully

---

### 7.3 Case Sensitivity
**Question:** Find meetings hosted by MARK ASHBY (all caps)

**Expected:** Should use UPPER() for case-insensitive matching

---

### 7.4 Limit Results
**Question:** Show me the first 5 events

**Expected:** Should use `WHERE ROWNUM <= 5` or `FETCH FIRST 5 ROWS ONLY`

---

## Category 8: Multi-Table Complex Queries

### 8.1 Full Event Details
**Question:** Show me complete details for "Oracle Open World 2023" including hosts, presenters, and revenue

**Expected:** Should JOIN multiple tables: `m_request_master` → `t_request_agenda_details` → `t_request_agenda_presenter` → `t_request_opportunity`

---

### 8.2 Host Performance
**Question:** Which host has organized the most meetings?

**Expected:** Should GROUP BY host name with COUNT and ORDER BY

---

### 8.3 Revenue by Industry
**Question:** What's the total revenue opportunity by industry?

**Expected:** Should JOIN opportunities to details and GROUP BY industry

---

## Category 9: CLOUD_DATE Specific Tests

### 9.1 Event Date Query
**Question:** Show me events happening on a specific date using event_date

**Expected:** Should use `event_date.ZONEDATE` for comparison (CLOUD_DATE handling)

---

### 9.2 Activity Date Range
**Question:** Show me agenda activities between two dates

**Expected:** Should use `t_request_agenda` CLOUD_DATE columns with `.ZONEDATE` attribute

---

### 9.3 Time-based Query
**Question:** Show me events with start times in the morning

**Expected:** Should handle `start_time` CLOUD_DATE column properly

---

## Category 10: Error-Prone Scenarios

### 10.1 Invalid Column Assumption
**Question:** Show me the start date of meetings in t_request_agenda_details

**Expected:** Should recognize that `t_request_agenda_details` has NO start_date and JOIN to `m_request_master`

---

### 10.2 CLOUD_DATE Direct Comparison
**Question:** Find events where start_date is after 2024-01-01

**Expected:** Should NOT compare CLOUD_DATE object directly; must use `.ZONEDATE` attribute

---

### 10.3 Missing Semicolon Handling
**Expected:** System should strip semicolons from generated SQL automatically

---

## Testing Strategy

1. **Start with Category 1-3** (Basic queries and JOINs) - Core functionality
2. **Test Category 4** (Custom fields) - LIKE pattern handling
3. **Test Category 9-10** (CLOUD_DATE & Edge cases) - Critical error scenarios
4. **Test Category 5-8** (Complex queries) - Advanced functionality

## Success Criteria

- ✅ No ORA-00904 errors (invalid identifier)
- ✅ No ORA-00932 errors (CLOUD_DATE comparison issues)
- ✅ Proper JOIN usage when dates needed from detail tables
- ✅ LIKE patterns used for custom fields
- ✅ No semicolons in final SQL
- ✅ Case-insensitive matching where appropriate
- ✅ Proper NULL handling

## Known Limitations to Document

Track which queries fail and why - this helps improve the system!

