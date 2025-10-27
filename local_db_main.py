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
    system_prompt="""You are a helpful SQL assistant for an Oracle database. 

**CRITICAL ORACLE DATABASE RULES:**
- NEVER END SQL STATEMENTS WITH SEMICOLON (;) — THIS WILL CAUSE ERRORS
- The Oracle driver will fail if you add semicolons to SQL statements
- Use `FETCH FIRST n ROWS ONLY` or `WHERE ROWNUM <= n` instead of LIMIT/OFFSET  
- Never use INFORMATION_SCHEMA (not in oracle)  
- Table/column names are UPPERCASE unless quoted  
- Strings use single quotes `'value'`  
- Prefer `NVL(expr1, expr2)` over COALESCE/IFNULL  
- Use explicit JOINs (`INNER JOIN`, `LEFT JOIN`)  
- For dates: `TO_DATE('YYYY-MM-DD', 'YYYY-MM-DD')` or `SYSDATE`  
- Default to `WHERE ROWNUM <= 10` when limiting  
- Generate only SELECT/READ queries unless asked otherwise

**CUSTOM FIELD SEARCH PATTERNS:**
- Custom fields (text_field_X) often contain formatted strings, not simple values
- ALWAYS use LIKE patterns for custom fields when user queries are vague or partial
- Examples: "COO presenters" → `text_field_3 LIKE '%COO%'`, "Halal dietary" → `text_field_3 LIKE '%Halal%'`
- Job titles are stored as "CIO - Chief Information Officer", not just "CIO"
- Dietary restrictions are in JSON arrays like ["Halal"] or quoted strings
- Company notes follow pattern "CompanyName Notes"
- When user asks for partial matches, abbreviations, or general terms, prefer LIKE over exact equality

**REMEMBER: NO SEMICOLONS AT THE END OF SQL STATEMENTS**

**SMART SEARCH STRATEGY:**
- For standard columns (first_name, last_name, email): Use exact matches when user provides full values
- For custom fields (text_field_X): Default to LIKE patterns unless user specifies exact format
- User says "CIO" → Use `LIKE '%CIO%'` (they likely mean the abbreviation within formatted text)
- User says "John Smith" → Use `= 'John'` and `= 'Smith'` (exact name match)
- User says "contains X" or "with X" → Always use LIKE patterns
- When in doubt about custom fields, use LIKE - it's more forgiving and finds more results

**UDT / OBJECT DATE RULES (CLOUD_DATE):**
- Some date/time columns are UDTs (e.g., `event_date`, `start_time`, `end_time`).
- NEVER compare or ORDER BY the object itself (e.g., `ORDER BY e.event_date`).
- Use a scalar attribute instead:
  - Day-level filters/sort: `e.event_date.ZONEDATE`
  - Exact UTC timestamp: `DATE '1970-01-01' + NUMTODSINTERVAL(e.event_date.UTCMS/1000,'SECOND')`
  - Local time: wrap with `FROM_TZ(...,'UTC') AT TIME ZONE e.event_date.ZONEID`
- Always qualify with table aliases to avoid ambiguity.

Focus on generating accurate Oracle SQL queries and provide clear explanations of results.
NEVER END SQL STATEMENTS WITH SEMICOLON (;) — THIS WILL CAUSE ERRORS """
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
    **MASTER REQUEST TABLE** - Central event management table (271 records).
    Contains: Event names, formats (In-Person, Virtual), status, dates, locations, 
    contact info (POC, email), technical requirements, custom fields (text_field_1-11, 
    number_field_1-10, date_field_1-10, boolean_field_1-5, text_area_field_1-5),
    dress codes, gift types, attendee counts, timezone info, event forms.
    Custom fields contain: text_field_1 (company names like TikTok, Broadcom, Cencora), 
    text_field_2 (company IDs), text_field_3 (JSON arrays of IDs). 
    IMPORTANT: Use start_date, end_date for date queries (NOT event_date, start_time, end_time 
    which are CLOUD_DATE UDT columns). CLOUD_DATE carries attributes: UTCMS (epoch ms UTC), ZONEID (IANA tz),
    ZONEDATE (DATE), ZONETIME (string). Prefer start_date/end_date for filtering. If you must use CLOUD_DATE,
    use the attribute explicitly: e.g., event_date.ZONEDATE for month/day filtering; for exact UTC timestamp use
    DATE '1970-01-01' + NUMTODSINTERVAL(event_date.UTCMS/1000, 'SECOND'). Always qualify with table alias.
    This is the PRIMARY table for all event/request management and tracking.
    """,
    
    "t_request_opportunity": """
    **REQUEST OPPORTUNITIES TABLE** - Sales opportunity tracking (31,020 records).
    Contains: Opportunity IDs, revenue data (opportunity_revenue, closed_opportunity_revenue),
    customer names, status, probability of close, quarter of close, 
    business development data, opportunity types, sales cycle info.
    Links to m_request_master via request_master_id. Key for revenue analysis.
    """,
    
    "t_request_agenda": """
    **REQUEST AGENDA TABLE** - Event agenda management (7,559 records).
    Contains: Agenda structure, meeting details, agenda items, schedule information,
    event timelines, agenda organization, custom fields for agenda data.
    Custom fields contain: text_field_1 (UUID identifiers), text_field_2 (agenda items like "Lunch - Executive Dining Room", "Reception - Special Menu", "Break - Beverages Only"), 
    text_field_3 (dietary restrictions in quotes like "Allergies - list special instructions", "Kosher").
    Use LIKE patterns for searching agenda items and dietary restrictions.
    Links to m_request_master. Manages the overall agenda structure for events.
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
    """,
    
    "t_event_activity_day": """
    **EVENT ACTIVITY DAY TABLE** - Daily event activities (2,772 records).
    Contains: Event dates, arrival/adjourn times, main room assignments,
    daily activity tracking, event scheduling, timestamp data.
    Links to m_request_master. Tracks day-by-day event activities.
    Note: event_date is a CLOUD_DATE UDT with attributes:
      - UTCMS (NUMBER epoch milliseconds UTC)
      - ZONEID (VARCHAR2 timezone id)
      - ZONEDATE (DATE component)
      - ZONETIME (VARCHAR2 time component)
    Guidance:
      - For range filters (e.g., next month), use e.event_date.ZONEDATE in comparisons.
      - For precise UTC timestamp, compute DATE '1970-01-01' + NUMTODSINTERVAL(e.event_date.UTCMS/1000,'SECOND').
      - For local time, wrap in FROM_TZ(..., 'UTC') AT TIME ZONE e.event_date.ZONEID.
      - Do NOT ORDER BY e.event_date (object). ORDER BY e.event_date.ZONEDATE or the computed UTC timestamp.
      - Always qualify columns with alias (e.).
    """,
    
    "m_user_role": """
    **USER ROLE MASTER TABLE** - User role assignments (2,051 records).
    Contains: User IDs, role IDs, request assignments, category info,
    access control, user permissions, role-based access to requests.
    Links to m_request_master. Manages user access and permissions.
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


