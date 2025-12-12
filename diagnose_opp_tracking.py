"""
Diagnostic script to investigate why opportunity/revenue queries are returning empty or null results
"""
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

ORACLE_CONNECTION_URI = (
    "oracle+oracledb://BIQ_EIQ_AURORA:BIQ_EIQ_AURORA"
    "@biqdb.ciqohztp4uck.us-west-2.rds.amazonaws.com:1521/?service_name=ORCL"
)

engine = create_engine(ORACLE_CONNECTION_URI)

def run_query(name, sql):
    print(f"\n{'='*80}")
    print(f"📊 {name}")
    print(f"{'='*80}")
    print(f"SQL: {sql[:200]}...")
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            rows = result.fetchall()
            columns = result.keys()
            print(f"\n✅ Returned {len(rows)} rows")
            if rows:
                print(f"Columns: {list(columns)}")
                print(f"\nSample data (first 5 rows):")
                for i, row in enumerate(rows[:5]):
                    print(f"  {i+1}. {dict(zip(columns, row))}")
            else:
                print("❌ No data returned!")
            return rows
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return None

print("\n" + "="*80)
print("🔍 DIAGNOSTIC: VW_OPP_TRACKING_REPORT TABLE ANALYSIS")
print("="*80)

# 1. Check table structure - what columns exist?
run_query("1. Column Names and Types in VW_OPP_TRACKING_REPORT",
    """SELECT column_name, data_type, data_length, nullable 
       FROM all_tab_columns 
       WHERE table_name = 'VW_OPP_TRACKING_REPORT' 
       ORDER BY column_id
       FETCH FIRST 50 ROWS ONLY"""
)

# 2. Check if there's ANY data in the table
run_query("2. Total Row Count in VW_OPP_TRACKING_REPORT",
    """SELECT COUNT(*) as total_rows FROM VW_OPP_TRACKING_REPORT"""
)

# 3. Check sample raw data
run_query("3. Sample Raw Data (first 3 rows)",
    """SELECT * FROM VW_OPP_TRACKING_REPORT FETCH FIRST 3 ROWS ONLY"""
)

# 4. Check PROBABILITYOFCLOSE - what values does it contain?
run_query("4. PROBABILITYOFCLOSE Values (Distinct)",
    """SELECT DISTINCT probabilityofclose, COUNT(*) as cnt
       FROM VW_OPP_TRACKING_REPORT
       WHERE probabilityofclose IS NOT NULL
       GROUP BY probabilityofclose
       ORDER BY cnt DESC
       FETCH FIRST 20 ROWS ONLY"""
)

# 5. Check what STATUS values exist
run_query("5. STATUS Values (Distinct)",
    """SELECT DISTINCT status, COUNT(*) as cnt
       FROM VW_OPP_TRACKING_REPORT
       WHERE status IS NOT NULL
       GROUP BY status
       ORDER BY cnt DESC
       FETCH FIRST 20 ROWS ONLY"""
)

# 6. Check revenue columns - are they populated?
run_query("6. Revenue Column Analysis (Non-Null Counts)",
    """SELECT 
         COUNT(initialopportunityrevenue) as initial_rev_count,
         COUNT(openopprevenue) as open_rev_count,
         COUNT(closed_opportunity_revenue) as closed_rev_count,
         SUM(CASE WHEN initialopportunityrevenue IS NOT NULL THEN 1 ELSE 0 END) as initial_not_null,
         SUM(CASE WHEN openopprevenue IS NOT NULL THEN 1 ELSE 0 END) as open_not_null,
         SUM(CASE WHEN closed_opportunity_revenue IS NOT NULL THEN 1 ELSE 0 END) as closed_not_null
       FROM VW_OPP_TRACKING_REPORT"""
)

# 7. Sample revenue data - what does it actually look like?
run_query("7. Sample Revenue Data (where any revenue is not null)",
    """SELECT eventid, customername, initialopportunityrevenue, openopprevenue, 
              closed_opportunity_revenue, probabilityofclose, status
       FROM VW_OPP_TRACKING_REPORT
       WHERE initialopportunityrevenue IS NOT NULL 
          OR openopprevenue IS NOT NULL 
          OR closed_opportunity_revenue IS NOT NULL
       FETCH FIRST 10 ROWS ONLY"""
)

# 8. Check probability column type and filtering
run_query("8. Probability of Close > 75% Test",
    """SELECT customername, probabilityofclose
       FROM VW_OPP_TRACKING_REPORT
       WHERE probabilityofclose IS NOT NULL
       FETCH FIRST 10 ROWS ONLY"""
)

# 9. Try numeric comparison on probability
run_query("9. Probability Numeric Comparison Test (try parsing)",
    """SELECT customername, probabilityofclose,
              CASE 
                WHEN REGEXP_LIKE(probabilityofclose, '^[0-9]+%?$') 
                THEN TO_NUMBER(REPLACE(probabilityofclose, '%', ''))
                ELSE NULL 
              END as prob_numeric
       FROM VW_OPP_TRACKING_REPORT
       WHERE probabilityofclose IS NOT NULL
       FETCH FIRST 10 ROWS ONLY"""
)

# 10. Check if probability is stored as string like "75%" vs number
run_query("10. Probability Column Data Type Check",
    """SELECT data_type, data_length 
       FROM all_tab_columns 
       WHERE table_name = 'VW_OPP_TRACKING_REPORT' 
         AND column_name = 'PROBABILITYOFCLOSE'"""
)

# 11. Check QUARTEROFCLOSE for Q4 2025 test
run_query("11. QUARTEROFCLOSE Values",
    """SELECT DISTINCT quarterofclose, COUNT(*) as cnt
       FROM VW_OPP_TRACKING_REPORT
       WHERE quarterofclose IS NOT NULL
       GROUP BY quarterofclose
       ORDER BY quarterofclose
       FETCH FIRST 20 ROWS ONLY"""
)

# 12. Check closed revenue by line of business
run_query("12. Revenue by Line of Business (where not null)",
    """SELECT lineofbusiness, 
              SUM(closed_opportunity_revenue) as total_closed_rev,
              COUNT(*) as event_count
       FROM VW_OPP_TRACKING_REPORT
       WHERE lineofbusiness IS NOT NULL
       GROUP BY lineofbusiness
       ORDER BY total_closed_rev DESC NULLS LAST
       FETCH FIRST 20 ROWS ONLY"""
)

print("\n" + "="*80)
print("🔍 DIAGNOSIS COMPLETE")
print("="*80)

