# Database Views Documentation

## Overview

The Q&A system uses **three Oracle database views** to provide access to event, attendee, and opportunity tracking data. These views are exposed through the `scripts/sqlite_qa.py` module.

---

## View Summary

| View Name                  | Purpose                                   | Row Count | Primary Use Case                                   |
| -------------------------- | ----------------------------------------- | --------- | -------------------------------------------------- |
| **VW_OPERATIONS_REPORT**   | Operations snapshot for events            | 216 rows  | Operational details and high-level event summaries |
| **VW_ATTENDEE_REPORT**     | Attendee roster per event                 | 398 rows  | Attendee lists, roles, remote/in-person breakdowns |
| **VW_OPP_TRACKING_REPORT** | Revenue & pipeline metrics tied to events | 216 rows  | Revenue, pipeline, or opportunity tracking         |

---

## 1. VW_OPERATIONS_REPORT

**Purpose**: Operations snapshot for events - provides comprehensive operational details and high-level event summaries.

### Column Structure (48 columns)

#### Event Metadata

- `EVENTID` - Event unique identifier
- `CUSTOMERNAME` - Customer name
- `PRIMARYOPPORTUNITY` - Primary opportunity ID
- `SECONDARYOPPORTUNITY` - Secondary opportunity (array)

#### Scheduling (Epoch Milliseconds)

- `EVENTDATE` - Event date
- `DURATION` - Duration of event (hours)
- `STARTDATE` - Start date (timezone object)
- `TIMEZONE` - Timezone information
- `STARTDATEMS` - Start date in milliseconds (epoch)
- `STARTTIME` - Start time object
- `STARTTIMEMS` - Start time in milliseconds (epoch)
- `ENDTIME` - End time object
- `ENDTIMEMS` - End time in milliseconds (epoch)
- `ACTSTARTTIME` - Actual start time object
- `ACTSTARTTIMEMS` - Actual start time in milliseconds
- `ACTENDTIME` - Actual end time object
- `ACTENDTIMEMS` - Actual end time in milliseconds

#### Logistics & Ownership

- `REQUESTEREMAIL` - Email of person who requested the event
- `ORACLEHOSTNAME` - Oracle host name
- `ORACLEHOSTEMAIL` - Oracle host email
- `ORACLEHOSTCELLPHONE` - Oracle host cell phone
- `ORACLEHOSTBUSINESSTITLE` - Oracle host's business title
- `TECHMANAGER` - Technical manager
- `BACKUPTECHMANAGER` - Backup technical manager
- `BRIEFINGMANAGER` - Briefing manager
- `PROGRAM` - Program name
- `COSTCENTER` - Cost center

#### Descriptors

- `FORMTYPE` - Form type (e.g., "Visit Information")
- `PILLARS` - Pillars (array)
- `ACCOUNTTYPE` - Account type (array)
- `LINEOFBUSINESS` - Line of business
- `VISITFOCUS` - Visit focus
- `REGION` - Region (e.g., EMEA, JAPAC, NAA)
- `TIER` - Tier level (e.g., Tier 1, N/A)
- `COUNTRY` - Country
- `CUSTOMERINDUSTRY` - Customer industry
- `COMPANYNAME` - Company name
- `COMPANYWEBSITE` - Company website
- `VISITTYPE` - Visit type
- `MEETINGOBJECTIVE` - Objective of the meeting
- `SALESPLAY` - Sales play (array)
- `STRATEGICCLIENTNAME` - Strategic client name
- `ISSTRATEGICCLIENT` - Whether client is strategic (Yes/No)
- `LASTDATEMETWITHES` - Last date met with ES
- `ALTERNATIVEDATE` - Alternative date
- `EXECUTIVESPONSER` - Executive sponsor
- `CHOOSEYESORNO` - Choose yes or no flag
- `AAAA` - Unknown field

### Important Notes

- **Date/Time Handling**: All date/time fields use epoch milliseconds. To convert to DATE for comparisons:
  ```sql
  DATE '1970-01-01' + NUMTODSINTERVAL(startdatems/1000, 'SECOND')
  ```
- **Example for today's meetings**:
  ```sql
  TRUNC(DATE '1970-01-01' + NUMTODSINTERVAL(startdatems/1000,'SECOND')) = TRUNC(SYSDATE)
  ```

### Use Cases

- Operational details and high-level event summaries
- Event scheduling and logistics information
- Customer and account information
- Resource assignment (managers, hosts)

---

## 2. VW_ATTENDEE_REPORT

**Purpose**: Attendee roster per event - provides detailed attendee information for each event.

### Column Structure (25 columns)

#### Event Metadata

- `EVENTID` - Event unique identifier
- `CUSTOMERNAME` - Customer name
- `PRIMARYOPPORTUNITY` - Primary opportunity ID
- `SECONDARYOPPORTUNITY` - Secondary opportunity (array)

#### Scheduling Info

- `EVENTDATE` - Event date
- `DURATION` - Duration of event (hours)
- `STARTDATE` - Start date
- `STARTDATEMS` - Start date in milliseconds (epoch)
- `STARTTIME` - Start time object
- `STARTTIMEMS` - Start time in milliseconds (epoch)
- `ENDTIME` - End time object
- `ENDTIMEMS` - End time in milliseconds (epoch)

#### Attendee Attributes

- `ATTENDEETYPE` - Type of attendee (Internal/External)
- `ISREMOTE` - Whether attendee is remote (Yes/No)
- `TRANSLATOR` - Whether attendee is a translator (Yes/No)
- `DECISIONMAKER` - Whether attendee is a decision maker (Yes/No)
- `INFLUENCER` - Whether attendee is an influencer (Yes/No)
- `ISTECHNICAL` - Whether attendee is technical (Yes/No)

#### Personal/Contact Info

- `FIRSTNAME` - First name
- `LASTNAME` - Last name
- `EMAIL` - Email address
- `PREFIX` - Name prefix (Mr, Ms, etc.)
- `BUSINESSTITLE` - Business title
- `CHIEFOFFICERTITLE` - C-level title (e.g., "CEO - Chief Executive Officer", "CFO - Chief Financial Officer")
- `COMPANY` - Company name

### Sample Data Examples

| EVENTID      | CUSTOMERNAME | ATTENDEETYPE | ISREMOTE | FIRSTNAME | LASTNAME | EMAIL                | BUSINESSTITLE            | DECISIONMAKER | INFLUENCER | ISTECHNICAL |
| ------------ | ------------ | ------------ | -------- | --------- | -------- | -------------------- | ------------------------ | ------------- | ---------- | ----------- |
| 731318026156 | Oracle       | Internal     | Yes      | Dan       | Boyd     | dan@briefingiq.com   | Project Manager          | No            | No         | No          |
| 731318026156 | Oracle       | External     | Yes      | Chris     | Henry    | chris@gmail.com      | Program Manager          | No            | No         | Yes         |
| 731318028051 | AT&T         | Internal     | Yes      | Hazel     | Phillips | hazel@briefingiq.com | Business Analyst         | No            | No         | No          |
| 731318028051 | AT&T         | External     | Yes      | Gina      | Medina   | gina@gmail.com       | Senior Software Engineer | No            | No         | Yes         |

### Important Notes

- **Date/Time Handling**: Convert ms values to DATE before comparing to SYSDATE or date ranges
- **Multiple Rows per Event**: Each attendee is a separate row, so one event can have multiple rows
- **C-Level Titles**: Stored in format like "CEO - Chief Executive Officer"

### Use Cases

- Attendee lists and rosters
- Role analysis (decision makers, influencers, technical)
- Remote vs in-person breakdowns
- Contact information for attendees
- C-level executive identification

---

## 3. VW_OPP_TRACKING_REPORT

**Purpose**: Revenue & pipeline metrics tied to events - provides opportunity tracking and revenue data.

### Column Structure (58 columns)

#### Event Metadata (Overlaps with Operations)

- `EVENTID` - Event unique identifier
- `CUSTOMERNAME` - Customer name
- `PRIMARYOPPORTUNITY` - Primary opportunity ID
- `SECONDARYOPPORTUNITY` - Secondary opportunity (array)
- `STARTTIMEMS`, `ENDTIMEMS`, `ACTSTARTTIMEMS`, `ACTENDTIMEMS` - Scheduling info

#### Opportunity Metrics

- `OPPNUMBER` - Opportunity number
- `STATUS` - Opportunity status
- `PROBABILITYOFCLOSE` - Probability of close (e.g., 75%, 90%)
- `QUARTEROFCLOSE` - Quarter of close
- `OPENDATE` - Open date (string)
- `CLOSEDATE` - Close date (string)

#### Revenue Fields

- `INITIALOPPORTUNITYREVENUE` - Initial opportunity revenue
- `OPENOPPREVENUE` - Open opportunity revenue
- `CLOSED_OPPORTUNITY_REVENUE` - Closed opportunity revenue
- `CHANGEINREVENUEDOLLAR` - Change in revenue (dollars)
- `CHANGEINREVENUEPERCENT` - Change in revenue (percentage)

#### Context Fields

- `FORMTYPE` - Form type
- `PILLARS` - Pillars (array)
- `ACCOUNTTYPE` - Account type (array)
- `LINEOFBUSINESS` - Line of business
- `REGION` - Region
- `PROGRAM` - Program
- `TIER` - Tier level
- `COSTCENTER` - Cost center
- `COUNTRY` - Country
- `CUSTOMERINDUSTRY` - Customer industry
- `VISITFOCUS` - Visit focus
- `MEETINGOBJECTIVE` - Meeting objective
- `SALESPLAY` - Sales play (array)
- `ISSTRATEGICCLIENT` - Strategic client flag (Yes/No)
- `STRATEGICCLIENTNAME` - Strategic client name
- `VISITTYPE` - Visit type
- `ORACLEHOSTNAME` - Oracle host name
- `ORACLEHOSTEMAIL` - Oracle host email
- `ORACLEHOSTCELLPHONE` - Oracle host cell phone
- `ORACLEHOSTBUSINESSTITLE` - Oracle host business title
- `TECHMANAGER` - Technical manager
- `BACKUPTECHMANAGER` - Backup technical manager
- `BRIEFINGMANAGER` - Briefing manager
- `EXECUTIVESPONSER` - Executive sponsor
- `REQUESTEREMAIL` - Requester email
- `COMPANYNAME` - Company name
- `COMPANYWEBSITE` - Company website
- `LASTDATEMETWITHES` - Last date met with ES
- `ALTERNATIVEDATE` - Alternative date
- `CHOOSEYESORNO` - Yes/No flag
- `AAAA` - Unknown field

### Sample Data Examples

| EVENTID      | CUSTOMERNAME | OPPNUMBER          | STATUS | PROBABILITYOFCLOSE | INITIALOPPORTUNITYREVENUE | OPENOPPREVENUE | CHANGEINREVENUEDOLLAR | CHANGEINREVENUEPERCENT |
| ------------ | ------------ | ------------------ | ------ | ------------------ | ------------------------- | -------------- | --------------------- | ---------------------- |
| 731318024100 | Grand Hotels | 006g5000000KxApAAK | NULL   | NULL               | NULL                      | NULL           | NULL                  | NULL                   |
| 731318025150 | Amazon       | 12344              | NULL   | NULL               | 95595                     | 732846854      | 732751259             | 766516.30%             |

### Important Notes

- **Date Handling**: For dates/times, rely on `*_MS` fields or `OPENDATE`/`CLOSEDATE` strings
- **Convert ms to DATE**: Convert epoch milliseconds to DATE before comparisons
- **Revenue Fields**: Can be NULL for opportunities without revenue data
- **Probability**: Stored as percentage (e.g., "75%", "90%")

### Use Cases

- Revenue and pipeline analysis
- Opportunity tracking
- Revenue forecasting
- Sales performance metrics
- Opportunity status monitoring

---

## Common Patterns Across Views

### Date/Time Conversion

All views use epoch milliseconds for date/time fields. To query by date:

```sql
-- For today's events
WHERE TRUNC(DATE '1970-01-01' + NUMTODSINTERVAL(startdatems/1000,'SECOND')) = TRUNC(SYSDATE)

-- For a specific month
WHERE EXTRACT(MONTH FROM (DATE '1970-01-01' + NUMTODSINTERVAL(startdatems/1000,'SECOND'))) = 10
AND EXTRACT(YEAR FROM (DATE '1970-01-01' + NUMTODSINTERVAL(startdatems/1000,'SECOND'))) = 2024
```

### Array Fields

Some fields contain arrays (e.g., `SECONDARYOPPORTUNITY`, `PILLARS`, `ACCOUNTTYPE`). These are stored as JSON arrays in the database.

### NULL Handling

Many fields can be NULL. Always use appropriate NULL handling in queries:

```sql
WHERE customername IS NOT NULL
```

---

## View Relationships

- **VW_OPERATIONS_REPORT** and **VW_OPP_TRACKING_REPORT** share the same `EVENTID` structure (both have 216 rows)
- **VW_ATTENDEE_REPORT** has more rows (398) because multiple attendees can be associated with one event
- All views share common fields: `EVENTID`, `CUSTOMERNAME`, `PRIMARYOPPORTUNITY`, `SECONDARYOPPORTUNITY`

---

## Query Examples

### Count meetings this month

```sql
SELECT COUNT(*)
FROM VW_OPERATIONS_REPORT
WHERE TRUNC(DATE '1970-01-01' + NUMTODSINTERVAL(startdatems/1000,'SECOND')) >= TRUNC(ADD_MONTHS(SYSDATE, 0), 'MM')
AND TRUNC(DATE '1970-01-01' + NUMTODSINTERVAL(startdatems/1000,'SECOND')) < TRUNC(ADD_MONTHS(SYSDATE, 1), 'MM')
FETCH FIRST 100 ROWS ONLY
```

### Get attendees for a customer

```sql
SELECT firstname, lastname, email, businesstitle, decisionmaker, influencer
FROM VW_ATTENDEE_REPORT
WHERE customername = 'Oracle'
FETCH FIRST 100 ROWS ONLY
```

### Revenue by line of business

```sql
SELECT lineofbusiness, SUM(openopprevenue) as total_revenue
FROM VW_OPP_TRACKING_REPORT
WHERE openopprevenue IS NOT NULL
GROUP BY lineofbusiness
FETCH FIRST 100 ROWS ONLY
```

---

## Notes for Q&A System

- The system automatically selects the appropriate view based on the question context
- SQL generation includes proper date conversions
- Results are limited to 100 rows by default
- Markdown tables are automatically generated for query results
