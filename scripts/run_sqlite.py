import sqlite3
import pandas as pd  # optional

conn = sqlite3.connect("data/oracle_views.db")

print("=== SQLite Schema ===")
schema_rows = conn.execute(
    "SELECT name, sql FROM sqlite_master WHERE type = 'table' ORDER BY name"
).fetchall()
for name, sql in schema_rows:
    print(f"\nTable: {name}\n{sql}")

print("\n=== Sample CLOUD_DATE columns ===")
df = pd.read_sql_query(
    """
    SELECT
        eventdate,
        startdate,
        starttime,
        endtime,
        actstarttime,
        actendtime
    FROM VW_OPERATIONS_REPORT
    LIMIT 5
    """,
    conn,
)
for idx, row in df.iterrows():
    print(idx, row["startdate"], row["starttime"], row["endtime"])

conn.close()