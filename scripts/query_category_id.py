"""
Query the database for category_id details.

Answers: What is category_id? Which values exist? Is there a lookup table?

Run: python scripts/query_category_id.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

ORACLE_CONNECTION_URI = os.getenv(
    "ORACLE_CONNECTION_URI",
    "oracle+oracledb://BIQ_EIQ_AURORA:BIQ_EIQ_AURORA"
    "@biqdb.ciqohztp4uck.us-west-2.rds.amazonaws.com:1521/?service_name=ORCL",
)


def main():
    engine = create_engine(ORACLE_CONNECTION_URI)
    print("=" * 70)
    print("CATEGORY_ID IN THE DATABASE")
    print("=" * 70)

    with engine.connect() as conn:
        # 1) Where does category_id appear?
        print("\n1) DISTINCT category_id and category_type_id in M_REQUEST_MASTER (with row counts)")
        print("-" * 70)
        q1 = """
        SELECT category_id, category_type_id, COUNT(*) AS event_count
        FROM M_REQUEST_MASTER
        GROUP BY category_id, category_type_id
        ORDER BY event_count DESC
        """
        try:
            r1 = conn.execute(text(q1))
            rows = r1.fetchall()
            for r in rows:
                print(f"   category_id={r[0]}, category_type_id={r[1]}  ->  {r[2]} events")
            if not rows:
                print("   (no rows)")
        except Exception as e:
            print(f"   Error: {e}")

        # 2) Look for a category lookup table (common names)
        print("\n2) TABLES THAT MIGHT DEFINE CATEGORY (names like %CATEGORY%)")
        print("-" * 70)
        q2 = """
        SELECT table_name FROM all_tables
        WHERE owner = USER AND UPPER(table_name) LIKE '%CATEGORY%'
        ORDER BY table_name
        """
        try:
            r2 = conn.execute(text(q2))
            tables = [row[0] for row in r2.fetchall()]
            if tables:
                for t in tables:
                    print(f"   {t}")
            else:
                # Try without owner filter (might be different schema)
                q2b = """
                SELECT owner, table_name FROM all_tables
                WHERE UPPER(table_name) LIKE '%CATEGORY%'
                AND ROWNUM <= 20
                """
                r2b = conn.execute(text(q2b))
                for row in r2b.fetchall():
                    print(f"   {row[0]}.{row[1]}")
        except Exception as e:
            print(f"   Error: {e}")

        # 3) If we have a category master, show id + name
        print("\n3) SAMPLE: category_id 512154 (used in VW_EVENT_PRESENTER – briefings filter)")
        print("-" * 70)
        q3 = """
        SELECT id, event_name, category_id, category_type_id, TEXT_FIELD_1
        FROM M_REQUEST_MASTER
        WHERE category_id = 512154 AND ROWNUM <= 5
        """
        try:
            r3 = conn.execute(text(q3))
            for row in r3.fetchall():
                print(f"   id={row[0]}, name={row[1][:40] if row[1] else 'N/A'}..., category_id={row[2]}, type_id={row[3]}, customer={row[4]}")
        except Exception as e:
            print(f"   Error: {e}")

        # 4) Category ID -> name (from M_CATEGORY)
        print("\n4) CATEGORY ID -> CATEGORY_NAME (from M_CATEGORY)")
        print("-" * 70)
        try:
            q4a = """
            SELECT id, category_name FROM M_CATEGORY
            WHERE id IN (512154, 1, 3, 10664, 2, 512155, 528150, 4, 5, 9200, 9202)
            ORDER BY id
            """
            r4a = conn.execute(text(q4a))
            for row in r4a.fetchall():
                print(f"   category_id={row[0]} -> {row[1]}")
        except Exception as e:
            print(f"   Error: {e}")

        # 5) Check if VW_OPERATIONS_REPORT exposes category
        print("\n5) COLUMNS IN VW_OPERATIONS_REPORT CONTAINING 'CATEGORY'")
        print("-" * 70)
        q5 = """
        SELECT column_name FROM all_tab_columns
        WHERE UPPER(table_name) = 'VW_OPERATIONS_REPORT'
        AND (owner = USER OR UPPER(owner) = 'BIQ_EIQ_AURORA')
        AND UPPER(column_name) LIKE '%CATEGORY%'
        ORDER BY column_id
        """
        try:
            r5 = conn.execute(text(q5))
            cols = [row[0] for row in r5.fetchall()]
            if cols:
                print("   " + ", ".join(cols))
            else:
                print("   (no such columns in view)")
        except Exception as e:
            print(f"   Error: {e}")

    print("\n" + "=" * 70)
    print("SUMMARY:")
    print("- category_id: numeric FK on M_REQUEST_MASTER; lookup in M_CATEGORY (id -> category_name).")
    print("- 512154 = 'Customer Briefing Request' (main briefings; used in VW_EVENT_PRESENTER filter).")
    print("- category_type_id: groups categories (e.g. 1 = briefings, 2 = calendar, 3 = EBC/Marketing/etc).")
    print("- VW_OPERATIONS_REPORT does not expose category; use M_REQUEST_MASTER or join M_CATEGORY for names.")
    print("- Frontend headers: x-cloud-categoryid (UUID in UNIQUE_ID?), x-cloud-categorytypeid (e.g. CATEGORY_TYPE_BRIEFINGS).")
    print("=" * 70)


if __name__ == "__main__":
    main()
