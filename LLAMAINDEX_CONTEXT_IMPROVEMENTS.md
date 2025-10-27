# LlamaIndex Context String Improvements for Q&A System

## Problem Analysis

**Original Issue**: Your LlamaIndex Q&A system was using the same generic Oracle database context for all tables, which didn't help the LLM understand the business purpose and content of each table.

**Error Explanation**: The context was focused only on SQL syntax rules rather than business meaning, making it difficult for the system to:

- Route queries to the most relevant tables
- Understand business context in questions
- Generate accurate SQL based on table purpose
- Provide meaningful explanations

## Solution: Table-Specific Context Strings

Based on the actual table analysis, I've created **table-specific context strings** that describe:

1. **Business Purpose**: What each table is used for
2. **Content Description**: What data it contains
3. **Record Counts**: Actual data volumes
4. **Key Fields**: Important columns and their purposes
5. **Relationships**: How tables connect to each other

## Improved Context Strings

### 1. **M_REQUEST_MASTER** (271 records)

```
**MASTER REQUEST TABLE** - Central event management table (271 records).
Contains: Event names, formats (In-Person, Virtual), status, dates, locations,
contact info (POC, email), technical requirements, custom fields (text_field_1-11,
number_field_1-10, date_field_1-10, boolean_field_1-5, text_area_field_1-5),
dress codes, gift types, attendee counts, timezone info, event forms.
This is the PRIMARY table for all event/request management and tracking.
```

### 2. **T_REQUEST_OPPORTUNITY** (31,020 records)

```
**REQUEST OPPORTUNITIES TABLE** - Sales opportunity tracking (31,020 records).
Contains: Opportunity IDs, revenue data (opportunity_revenue, closed_opportunity_revenue),
customer names, status, probability of close, quarter of close,
business development data, opportunity types, sales cycle info.
Links to m_request_master via request_master_id. Key for revenue analysis.
```

### 3. **T_REQUEST_AGENDA** (7,559 records)

```
**REQUEST AGENDA TABLE** - Event agenda management (7,559 records).
Contains: Agenda structure, meeting details, agenda items, schedule information,
event timelines, agenda organization, custom fields for agenda data.
Links to m_request_master. Manages the overall agenda structure for events.
```

### 4. **T_REQUEST_AGENDA_DETAILS** (7,695 records)

```
**REQUEST AGENDA DETAILS TABLE** - Detailed meeting information (7,695 records).
Contains: Meeting details, host information, customer data, sales division,
account info, industry, meeting focus, attendee counts, booking IDs,
revenue influenced data, meeting objectives, conference experience,
C-level attendee flags, hybrid meeting indicators, extensive custom fields.
Links to t_request_agenda and m_request_master. Rich meeting context data.
```

### 5. **T_REQUEST_AGENDA_PRESENTER** (12,725 records)

```
**REQUEST AGENDA PRESENTER TABLE** - Presenter/speaker management (12,725 records).
Contains: Presenter details (first_name, last_name, title, email),
designation, presenter type, calendar invite status, notification status,
presenter order, contact info, custom fields (text_field_1-10, etc.).
Links to t_request_agenda and m_request_master. Manages speaker assignments.
```

### 6. **T_EVENT_ACTIVITY_DAY** (2,772 records)

```
**EVENT ACTIVITY DAY TABLE** - Daily event activities (2,772 records).
Contains: Event dates, arrival/adjourn times, main room assignments,
daily activity tracking, event scheduling, timestamp data.
Links to m_request_master. Tracks day-by-day event activities.
```

### 7. **M_USER_ROLE** (2,051 records)

```
**USER ROLE MASTER TABLE** - User role assignments (2,051 records).
Contains: User IDs, role IDs, request assignments, category info,
access control, user permissions, role-based access to requests.
Links to m_request_master. Manages user access and permissions.
```

## Key Improvements

### ✅ **Business Understanding**

- Each table now has context that explains its business purpose
- The LLM understands what each table contains and why it exists
- Better domain-specific terminology and concepts

### ✅ **Data Volume Awareness**

- Record counts help the LLM understand table importance and size
- Better query optimization based on data volumes
- More appropriate JOIN strategies

### ✅ **Relationship Mapping**

- Clear understanding of how tables relate to each other
- Better JOIN logic in generated SQL
- More accurate query routing

### ✅ **Field-Specific Context**

- Understanding of custom fields (text_field_1-11, etc.)
- Knowledge of key business fields (revenue, status, dates)
- Better column selection for queries

## Expected Benefits

### 🎯 **Query Accuracy**

- More accurate table selection for complex queries
- Better understanding of business context in questions
- Improved SQL generation quality

### 🎯 **Context-Aware Responses**

- Better explanations of results
- More relevant data retrieval
- Enhanced business domain understanding

### 🎯 **Performance Optimization**

- Smarter query routing to most relevant tables
- Better use of indexes and relationships
- More efficient SQL generation

## Usage Examples

With these improvements, your Q&A system can now better handle queries like:

- **"What events are scheduled for this month?"** → Routes to `m_request_master` with date filtering
- **"Show me all presenters for upcoming events"** → Routes to `t_request_agenda_presenter` with JOINs
- **"Which events have the highest opportunity value?"** → Routes to `t_request_opportunity` for revenue analysis
- **"What are the different user roles in the system?"** → Routes to `m_user_role` for role information

## Implementation

The improved context strings are now implemented in `local_db_main.py` with:

- Oracle database rules maintained for proper SQL generation
- Table-specific business context for each table
- Combined context that provides both technical and business understanding

This approach follows LlamaIndex best practices for providing context **before generation** rather than during table context initialization, ensuring the LLM has comprehensive understanding of your data structure and business domain.
