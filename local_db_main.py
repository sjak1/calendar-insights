from sqlalchemy import (
    create_engine,
    MetaData,
    Table,
    Column,
    String,
    Integer,
    select,
    inspect,
)
from sqlalchemy.dialects.oracle.base import ischema_names
from sqlalchemy.types import Date

from llama_index.core.indices.struct_store.sql_query import (
    SQLTableRetrieverQueryEngine,
)

from llama_index.core.objects import (
    SQLTableNodeMapping,
    ObjectIndex,
    SQLTableSchema 
)

from llama_index.core import VectorStoreIndex
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.core import SQLDatabase
from llama_index.llms.openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Map CLOUD_DATE to standard DATE type to avoid Oracle UDT errors
ischema_names["CLOUD_DATE"] = Date

write_acc = "biqdb.ciqohztp4uck.us-west-2.rds.amazonaws.com"
read_acc =  "biq-read.ciqohztp4uck.us-west-2.rds.amazonaws.com"

engine = create_engine("oracle+oracledb://BIQ_EIQ_AURORA:BIQ_EIQ_AURORA@biqdb.ciqohztp4uck.us-west-2.rds.amazonaws.com:1521/?service_name=ORCL")
meta = MetaData()
meta.reflect(bind=engine)

my_table = meta.tables['m_report_param_mapping']

'''with engine.connect() as conn:
    #print("meta table keys here :: ")
    #print(meta.tables.keys())
    #rows = conn.execute(my_table.select()).fetchall()
    #print(rows)
    for column in my_table.columns:
        print(column.name, column.type)'''

llm = OpenAI(
    temperature=0.7, 
    model="gpt-4.1-mini",
    system_prompt="""You are a SQL assistant for an Oracle database with CRITICAL RULES that MUST be followed.

═══════════════════════════════════════════════════════════════════
🚨 CRITICAL RULES - VIOLATIONS WILL CAUSE QUERY FAILURES 🚨
═══════════════════════════════════════════════════════════════════

1. ❌ NO SEMICOLONS - NEVER end SQL with semicolon (;) - Oracle driver will reject it
   ✅ Correct: SELECT * FROM table WHERE ROWNUM <= 10
   ❌ Wrong: SELECT * FROM table WHERE ROWNUM <= 10;

2. ❌ NO DIRECT ORDERING ON CLOUD_DATE UDT - Will cause ORA-22950 error
   ✅ Correct: ORDER BY e.event_date.ZONEDATE
   ❌ Wrong: ORDER BY e.event_date
   
   🔥 CLOUD_DATE columns (MUST use .ZONEDATE for ORDER BY):
   - t_event_activity_day: EVENT_DATE, ARRIVAL_TS, ADJOURN_TS
   - t_request_agenda: START_TIME, ACTIVITY_DATE, ACTIVITY_END_DATE, ACTIVITY_START_DATE, END_TIME  
   - m_request_master: EVENT_DATE, START_DATE, START_TIME, END_TIME
   
   For comparisons/filters: column.ZONEDATE
   For sorting: ORDER BY column.ZONEDATE
   For UTC timestamp: DATE '1970-01-01' + NUMTODSINTERVAL(column.UTCMS/1000,'SECOND')

3. 📋 TABLE SELECTION FOR "EVENTS" QUERIES:
   ✅ Default to: m_request_master (main events table with event names, status, POC)
   ⚠️ Only use t_event_activity_day for: daily activity schedules, arrival/adjourn times

4. 🗓️ DATE FILTERING WITH CLOUD_DATE:
   - When comparing or filtering dates from CLOUD_DATE columns (e.g., start_date, event_date):
     * Use the scalar attribute: column.ZONEDATE
     * For current month: TRUNC(column.ZONEDATE, 'MM') = TRUNC(SYSDATE, 'MM')
     * For ranges: column.ZONEDATE BETWEEN TRUNC(SYSDATE, 'MM') AND LAST_DAY(SYSDATE)
   - Avoid EXTRACT on the raw UDT; always reference the scalar attribute first.
   - Assign a table alias (e.g., m.start_date.ZONEDATE) when the table has one.
   
═══════════════════════════════════════════════════════════════════

**ORACLE SYNTAX RULES:**
- Use `FETCH FIRST n ROWS ONLY` or `WHERE ROWNUM <= n` (NOT LIMIT)
- Never use INFORMATION_SCHEMA (doesn't exist in Oracle)
- Table/column names are UPPERCASE unless quoted
- Strings use single quotes: 'value' not "value"
- Use NVL(expr1, expr2) for null handling
- Use explicit JOINs: INNER JOIN, LEFT JOIN
- Dates: TO_DATE('YYYY-MM-DD', 'YYYY-MM-DD') or SYSDATE
- Generate only SELECT/READ queries unless asked otherwise

**CUSTOM FIELD SEARCH (text_field_X, text_area_field_X):**
- Custom fields contain formatted strings, not simple values
- ALWAYS use LIKE for custom field searches:
  * "CIO" → text_field_3 LIKE '%CIO%' (job titles stored as "CIO - Chief Information Officer")
  * "Halal" → text_field_3 LIKE '%Halal%' (dietary in JSON arrays like ["Halal"])
  * "COO presenters" → text_field_3 LIKE '%COO%'
- Standard columns (first_name, last_name, email): use exact matches (=)
- When in doubt with text_field_X: prefer LIKE over =

**QUERY EXAMPLES:**
✅ Good: SELECT id, event_name, status FROM m_request_master WHERE ROWNUM <= 10
✅ Good: SELECT id, e.event_date.ZONEDATE as event_date FROM t_event_activity_day e ORDER BY e.event_date.ZONEDATE FETCH FIRST 10 ROWS ONLY
✅ Good: SELECT * FROM t_request_agenda_presenter WHERE text_field_3 LIKE '%CIO%'
❌ Bad: SELECT * FROM t_event_activity_day ORDER BY event_date; (semicolon + UDT ordering)

Focus on accurate Oracle SQL generation. Double-check: no semicolons, CLOUD_DATE uses .ZONEDATE for ORDER BY."""
)

# Custom SQLDatabase that can modify generated SQL before execution
class ModifyingSQLDatabase(SQLDatabase):
    def _strip_trailing_semicolon(self, sql: str) -> str:
        return sql.rstrip().rstrip(';')

    def _modify_sql(self, command: str) -> str:
        original = command
        sql = self._strip_trailing_semicolon(command)
        if sql != original:
            print("[SQL modify] original:", original)
            print("[SQL modify] modified:", sql)
        return sql

    def run_sql(self, command: str):
        modified = self._modify_sql(command)
        return super().run_sql(modified)

sql_database = ModifyingSQLDatabase(engine, include_tables=[
    "t_request_opportunity",
    "t_request_agenda_presenter", 
    "t_request_agenda_details",
    "t_request_agenda",
    "m_user_role",
    "t_event_activity_day",
    "m_request_master"
]) 


# Oracle database context for SQL generation
oracle_context = """
**ORACLE DATABASE RULES:**
- DO NOT END STATEMENTS WITH SEMICOLON (;) — IT WILL ERROR
- Use `FETCH FIRST n ROWS ONLY` or `WHERE ROWNUM <= n` instead of LIMIT/OFFSET  
- Never use INFORMATION_SCHEMA (not in oracle)  
- Table/column names are UPPERCASE unless quoted  
- Strings use single quotes `'value'`  
- Prefer `NVL(expr1, expr2)` over COALESCE/IFNULL  
- Use explicit JOINs (`INNER JOIN`, `LEFT JOIN`)  
- For dates: `TO_DATE('YYYY-MM-DD', 'YYYY-MM-DD')` or `SYSDATE`  
- Default to `WHERE ROWNUM <= 10` when limiting  
- Generate only SELECT/READ queries unless asked otherwise
"""

# Table-specific context strings based on actual table analysis
table_contexts = {
    "m_request_master": """
    🎯 **PRIMARY EVENTS TABLE** - USE THIS FOR "show me events" queries! (271 records)
    
    This is the MAIN table for event information. Contains:
    - Event identification: id, event_name, event_code, status
    - Event details: format (In-Person/Virtual), location, timezone
    - Contact info: poc (Point of Contact), poc_email
    - Dates: start_date, end_date (these are CLOUD_DATE UDT columns with .ZONEDATE scalar)
      * For month-based filters: TRUNC(m.start_date.ZONEDATE, 'MM') = TRUNC(SYSDATE, 'MM')
      * For ranges: m.start_date.ZONEDATE BETWEEN TRUNC(SYSDATE, 'MM') AND LAST_DAY(SYSDATE)
    - Custom fields: text_field_1-11 (company names like TikTok, Broadcom), 
      number_field_1-10, date_field_1-10, boolean_field_1-5, text_area_field_1-5
    - Other: dress_code, gift_type, attendee_count, technical_requirements
    
    ⚠️ CLOUD_DATE UDT columns (require .ZONEDATE for ORDER BY / filters):
    - EVENT_DATE, START_DATE, START_TIME, END_TIME
    - Never ORDER BY these directly → causes ORA-22950 error
    - Use: ORDER BY m.event_date.ZONEDATE (with table alias)
    - UDT attributes: .UTCMS, .ZONEID, .ZONEDATE, .ZONETIME
    
    💡 WHEN TO USE THIS TABLE:
    ✅ "Show me events" → SELECT id, event_name, status FROM m_request_master
    ✅ "Event names and formats" → SELECT event_name, format FROM m_request_master
    ✅ "Events this month" → SELECT id, event_name FROM m_request_master m WHERE TRUNC(m.start_date.ZONEDATE, 'MM') = TRUNC(SYSDATE, 'MM')
    ✅ "Events for company X" → SELECT * FROM m_request_master WHERE text_field_1 LIKE '%X%'
    ❌ Don't use for: daily activity schedules (use t_event_activity_day instead)
    """,
    
    "t_request_opportunity": """
    **REQUEST OPPORTUNITIES TABLE** - Sales opportunity tracking (31,020 records).
    Contains: Opportunity IDs, revenue data (opportunity_revenue, closed_opportunity_revenue),
    customer names, status, probability of close, quarter of close, 
    business development data, opportunity types, sales cycle info.
    Links to m_request_master via request_master_id. Key for revenue analysis.
    CLOUD_DATE columns: None
    """,
    
    "t_request_agenda": """
    **REQUEST AGENDA TABLE** - Event agenda management (7,559 records).
    Contains: Agenda structure, meeting details, agenda items, schedule information,
    event timelines, agenda organization, custom fields for agenda data.
    Custom fields contain: text_field_1 (UUID identifiers), text_field_2 (agenda items like "Lunch - Executive Dining Room", "Reception - Special Menu", "Break - Beverages Only"), 
    text_field_3 (dietary restrictions in quotes like "Allergies - list special instructions", "Kosher").
    Use LIKE patterns for searching agenda items and dietary restrictions.
    Links to m_request_master. Manages the overall agenda structure for events.
    CLOUD_DATE columns: START_TIME, ACTIVITY_DATE, ACTIVITY_END_DATE, ACTIVITY_START_DATE, END_TIME
    CLOUD_DATE UDT attributes:
      - UTCMS (NUMBER epoch milliseconds UTC)
      - ZONEID (VARCHAR2 timezone id)
      - ZONEDATE (DATE component)
      - ZONETIME (VARCHAR2 time component)
    """,
    
    "t_request_agenda_details": """
    **REQUEST AGENDA DETAILS TABLE** - Detailed meeting information (7,695 records).
    Contains: Meeting details, host information, customer data, sales division,
    account info, industry, meeting focus, attendee counts, booking IDs,
    revenue influenced data, meeting objectives, conference experience,
    C-level attendee flags, hybrid meeting indicators, extensive custom fields.
    Key populated fields: host_first_name, host_last_name, host_email, account_name, 
    industry, meeting_focus, number_of_attendees. 
    Custom fields contain: text_field_1 (meal/event types like "Reception - Special Menu", "Break - Beverages Only"), 
    text_field_2 (titles like "Ms.", "Mr."), text_field_3 (JSON arrays of dietary restrictions like ["Halal"], ["Kosher"], ["Vegan - list special instructions"]),
    text_field_4 (company notes like "AllianceIT Notes", "PayPal Notes"), text_field_5 (additional attendees). 
    Note: meeting_id and customer_company are often NULL. For text_field_3, use LIKE '%Halal%' patterns for dietary searches.
    Links to t_request_agenda and m_request_master. Rich meeting context data.
    CLOUD_DATE columns: None
    """,
    
    "t_request_agenda_presenter": """
    **REQUEST AGENDA PRESENTER TABLE** - Presenter/speaker management (12,725 records).
    Contains: Presenter details (first_name, last_name, title, email), 
    designation, presenter type, calendar invite status, notification status,
    presenter order, contact info, custom fields (text_field_1-10, etc.).
    Custom fields contain: text_field_1 (status like Pending, Declined), 
    text_field_2 (email addresses), text_field_3 (full job titles like "CIO - Chief Information Officer", "CISO - Chief Information Security Officer", "CRO - Chief Risk Officer", "COO - Chief Operating Officer").
    IMPORTANT: For text_field_3 searches, use LIKE '%CIO%' or '%CISO%' patterns, not exact matches.
    Links to t_request_agenda and m_request_master. Manages speaker assignments.
    CLOUD_DATE columns: None
    """,
    
    "t_event_activity_day": """
    ⚠️ **EVENT ACTIVITY DAY TABLE** - Daily schedules only! (2,772 records)
    
    Contains: Daily activity dates, arrival/adjourn times, main room assignments.
    Links to m_request_master (request_master_id).
    
    🔥 ALL columns are CLOUD_DATE UDT (require .ZONEDATE for ORDER BY):
    - EVENT_DATE, ARRIVAL_TS, ADJOURN_TS
    - NEVER ORDER BY e.event_date → causes ORA-22950 error
    - ALWAYS ORDER BY e.event_date.ZONEDATE
    - UDT attributes: .UTCMS, .ZONEID, .ZONEDATE, .ZONETIME
    
    💡 WHEN TO USE THIS TABLE:
    ✅ "Daily activity schedules" → Use this table
    ✅ "Arrival and adjourn times" → Use this table
    ✅ "Main room assignments by day" → Use this table
    ❌ "Show me events" → Use m_request_master instead!
    ❌ "Event names/formats/status" → Use m_request_master instead!
    
    Example correct query:
    SELECT e.id, e.event_date.ZONEDATE as activity_date, e.main_room
    FROM t_event_activity_day e
    ORDER BY e.event_date.ZONEDATE
    FETCH FIRST 10 ROWS ONLY
    """,
    
    "m_user_role": """
    **USER ROLE MASTER TABLE** - User role assignments (2,051 records).
    Contains: User IDs, role IDs, request assignments, category info,
    access control, user permissions, role-based access to requests.
    Links to m_request_master. Manages user access and permissions.
    CLOUD_DATE columns: None
    """
}

table_node_mapping = SQLTableNodeMapping(sql_database)
table_schema_objs = [
    SQLTableSchema(
        table_name="m_request_master", 
        context_str= table_contexts["m_request_master"]
    ),
    SQLTableSchema(
        table_name="t_request_opportunity", 
        context_str= table_contexts["t_request_opportunity"]
    ),
    SQLTableSchema(
        table_name="t_request_agenda", 
        context_str= table_contexts["t_request_agenda"]
    ),
    SQLTableSchema(
        table_name="t_request_agenda_details", 
        context_str= table_contexts["t_request_agenda_details"]
    ),
    SQLTableSchema(
        table_name="t_request_agenda_presenter", 
        context_str= table_contexts["t_request_agenda_presenter"]
    ),
    SQLTableSchema(
        table_name="t_event_activity_day", 
        context_str= table_contexts["t_event_activity_day"]
    ),
    SQLTableSchema(
        table_name="m_user_role", 
        context_str= table_contexts["m_user_role"]
    )
]

obj_index = ObjectIndex.from_objects(
    table_schema_objs,
    table_node_mapping,
    VectorStoreIndex,
    embed_model=OpenAIEmbedding(model="text-embedding-3-small"),
)

query_engine = SQLTableRetrieverQueryEngine(
    sql_database, obj_index.as_retriever(similarity_top_k=1), verbose=True
)


