from sqlalchemy import create_engine, text, inspect
from sqlalchemy.dialects.oracle.base import ischema_names
from sqlalchemy.types import Date

# Map CLOUD_DATE to standard DATE type
ischema_names["CLOUD_DATE"] = Date

engine = create_engine("oracle+oracledb://BIQ_EIQ_AURORA:BIQ_EIQ_AURORA@biq-read.ciqohztp4uck.us-west-2.rds.amazonaws.com:1521/?service_name=ORCL")

# Get column information
inspector = inspect(engine)
columns = inspector.get_columns('m_request_master')

print("M_REQUEST_MASTER columns:")
print("=" * 80)
for col in columns:
    print(f"{col['name']:<30} {str(col['type']):<30}")

# Try the actual query
print("\n\nTesting the modified query:")
print("=" * 80)

# Try different approaches
test_queries = [
    ("Simple SELECT", """
SELECT e.id, e.event_name
FROM m_request_master e
WHERE ROWNUM <= 5
"""),
    ("With l_start_date", """
SELECT e.id, e.event_name, e.l_start_date
FROM m_request_master e
WHERE e.l_start_date >= TO_DATE('2024-01-01', 'YYYY-MM-DD') 
  AND e.l_start_date < TO_DATE('2024-04-01', 'YYYY-MM-DD')
  AND ROWNUM <= 5
"""),
    ("With start_date.ZONEDATE", """
SELECT e.id, e.event_name
FROM m_request_master e
WHERE e.start_date.ZONEDATE >= TO_DATE('2024-01-01', 'YYYY-MM-DD') 
  AND e.start_date.ZONEDATE < TO_DATE('2024-04-01', 'YYYY-MM-DD')
  AND ROWNUM <= 5
"""),
]

for name, query in test_queries:
    print(f"\n{name}:")
    print("-" * 80)
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query))
            rows = result.fetchall()
            print(f"✓ Success! Found {len(rows)} rows")
            for row in rows:
                print(row)
    except Exception as e:
        print(f"✗ Error: {e}")

