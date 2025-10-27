from sqlalchemy import create_engine, text
import pandas as pd
from collections import Counter

# Database connection
engine = create_engine("oracle+oracledb://BIQ_EIQ_AURORA:BIQ_EIQ_AURORA@biqdb.ciqohztp4uck.us-west-2.rds.amazonaws.com:1521/?service_name=ORCL")

def analyze_custom_fields(table_name, field_prefix="text_field"):
    """Analyze custom fields (text_field_1, date_field_1, etc.) to see what data they contain"""
    print(f"\n{'='*80}")
    print(f"ANALYZING CUSTOM FIELDS IN: {table_name.upper()}")
    print(f"{'='*80}")
    
    # Get all custom field columns
    custom_fields = []
    field_types = ['text_field', 'date_field', 'number_field', 'boolean_field', 'text_area_field']
    
    for field_type in field_types:
        for i in range(1, 21):  # Check fields 1-20
            field_name = f"{field_type}_{i}"
            custom_fields.append(field_name)
    
    # Build query to check which fields have data
    field_checks = []
    for field in custom_fields:
        field_checks.append(f"CASE WHEN {field} IS NOT NULL THEN 1 ELSE 0 END as has_{field}")
    
    query = f"""
    SELECT 
        COUNT(*) as total_rows,
        {', '.join(field_checks)}
    FROM {table_name}
    WHERE ROWNUM <= 1000
    """
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query))
            row = result.fetchone()
            
            print(f"Total rows analyzed: {row[0]}")
            print(f"\nFIELD USAGE ANALYSIS:")
            print("-" * 60)
            
            # Check which fields have data
            populated_fields = []
            for i, field in enumerate(custom_fields, 1):
                has_data = row[i]
                if has_data > 0:
                    populated_fields.append(field)
                    print(f"  {field:<20} - {has_data} rows have data")
            
            if not populated_fields:
                print("  No custom fields contain data in the sample")
                return []
            
            # Get sample data from populated fields
            print(f"\nSAMPLE DATA FROM POPULATED CUSTOM FIELDS:")
            print("-" * 60)
            
            sample_query = f"""
            SELECT {', '.join(populated_fields[:10])}  -- Limit to first 10 fields for readability
            FROM {table_name}
            WHERE ({' OR '.join([f"{field} IS NOT NULL" for field in populated_fields[:10]])})
            AND ROWNUM <= 5
            """
            
            result = conn.execute(text(sample_query))
            rows = result.fetchall()
            columns = result.keys()
            
            if rows:
                # Print column headers
                header = " | ".join([col[:15].ljust(15) for col in columns])
                print(header)
                print("-" * len(header))
                
                # Print sample rows
                for row in rows:
                    row_str = " | ".join([str(val)[:15].ljust(15) if val is not None else "NULL".ljust(15) for val in row])
                    print(row_str)
            
            return populated_fields
            
    except Exception as e:
        print(f"Error analyzing {table_name}: {str(e)}")
        return []

def analyze_master_table_structure():
    """Deep dive into M_REQUEST_MASTER table structure"""
    print(f"\n{'='*80}")
    print("DEEP DIVE: M_REQUEST_MASTER TABLE STRUCTURE")
    print(f"{'='*80}")
    
    # Core business fields analysis
    core_fields_query = """
    SELECT 
        event_name,
        event_format,
        status,
        dress_code,
        gift_type,
        poc,
        city,
        email,
        requester_email,
        category_type_id,
        category_id,
        location_id,
        l_start_date,
        l_end_date,
        duration,
        timezone_id,
        tenant_id
    FROM m_request_master
    WHERE ROWNUM <= 10
    """
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text(core_fields_query))
            rows = result.fetchall()
            columns = result.keys()
            
            print("CORE BUSINESS FIELDS SAMPLE:")
            print("-" * 80)
            
            if rows:
                # Print column headers
                header = " | ".join([col[:12].ljust(12) for col in columns])
                print(header)
                print("-" * len(header))
                
                # Print sample rows
                for row in rows:
                    row_str = " | ".join([str(val)[:12].ljust(12) if val is not None else "NULL".ljust(12) for val in row])
                    print(row_str)
                    
    except Exception as e:
        print(f"Error in core fields analysis: {str(e)}")

def analyze_field_patterns():
    """Analyze patterns in custom fields across tables"""
    tables_to_analyze = [
        "m_request_master",
        "t_request_agenda_presenter", 
        "t_request_agenda_details",
        "t_request_agenda"
    ]
    
    print(f"\n{'='*80}")
    print("CUSTOM FIELD PATTERNS ACROSS ALL TABLES")
    print(f"{'='*80}")
    
    all_populated_fields = {}
    
    for table in tables_to_analyze:
        print(f"\n--- {table.upper()} ---")
        populated_fields = analyze_custom_fields(table)
        all_populated_fields[table] = populated_fields
    
    # Summary of field usage patterns
    print(f"\n{'='*80}")
    print("FIELD USAGE SUMMARY")
    print(f"{'='*80}")
    
    for table, fields in all_populated_fields.items():
        if fields:
            print(f"\n{table}:")
            # Group fields by type
            field_types = {}
            for field in fields:
                field_type = field.split('_')[0] + '_field'
                if field_type not in field_types:
                    field_types[field_type] = []
                field_types[field_type].append(field)
            
            for field_type, field_list in field_types.items():
                print(f"  {field_type}: {', '.join(field_list)}")

def analyze_data_types_and_constraints():
    """Analyze data types and constraints in key tables"""
    print(f"\n{'='*80}")
    print("DATA TYPES AND CONSTRAINTS ANALYSIS")
    print(f"{'='*80}")
    
    # Get detailed column information
    query = """
    SELECT 
        table_name,
        column_name,
        data_type,
        data_length,
        nullable,
        data_default
    FROM user_tab_columns 
    WHERE table_name IN ('M_REQUEST_MASTER', 'T_REQUEST_OPPORTUNITY', 'T_REQUEST_AGENDA_PRESENTER', 'T_REQUEST_AGENDA_DETAILS', 'T_REQUEST_AGENDA', 'M_USER_ROLE', 'T_EVENT_ACTIVITY_DAY')
    AND (column_name LIKE '%FIELD%' OR column_name IN ('event_name', 'status', 'created_by', 'updated_by', 'unique_id'))
    ORDER BY table_name, column_name
    """
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query))
            rows = result.fetchall()
            
            print("CUSTOM FIELDS AND KEY COLUMNS:")
            print("-" * 100)
            print(f"{'Table':<25} {'Column':<25} {'Type':<15} {'Length':<8} {'Nullable':<10} {'Default'}")
            print("-" * 100)
            
            for row in rows:
                table, column, data_type, length, nullable, default = row
                default_str = str(default)[:20] if default else 'NULL'
                print(f"{table:<25} {column:<25} {data_type:<15} {str(length):<8} {nullable:<10} {default_str}")
                
    except Exception as e:
        print(f"Error in data types analysis: {str(e)}")

def analyze_sample_data_values():
    """Analyze actual values in key fields to understand data patterns"""
    print(f"\n{'='*80}")
    print("SAMPLE DATA VALUES ANALYSIS")
    print(f"{'='*80}")
    
    # Analyze event formats
    print("\nEVENT FORMATS:")
    print("-" * 40)
    query = """
    SELECT event_format, COUNT(*) as count
    FROM m_request_master 
    WHERE event_format IS NOT NULL
    GROUP BY event_format
    ORDER BY count DESC
    """
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query))
            rows = result.fetchall()
            
            for row in rows:
                print(f"  {row[0]:<20} - {row[1]} events")
                
    except Exception as e:
        print(f"Error in event format analysis: {str(e)}")
    
    # Analyze status values
    print("\nSTATUS VALUES:")
    print("-" * 40)
    query = """
    SELECT status, COUNT(*) as count
    FROM m_request_master 
    WHERE status IS NOT NULL
    GROUP BY status
    ORDER BY count DESC
    """
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query))
            rows = result.fetchall()
            
            for row in rows:
                print(f"  {row[0]:<20} - {row[1]} records")
                
    except Exception as e:
        print(f"Error in status analysis: {str(e)}")

def main():
    """Main analysis function"""
    print("DEEP DATA STRUCTURE ANALYSIS")
    print("=" * 80)
    
    # Test connection
    try:
        with engine.connect() as conn:
            print("✓ Database connection successful")
    except Exception as e:
        print(f"✗ Database connection failed: {str(e)}")
        return
    
    # Run all analyses
    analyze_master_table_structure()
    analyze_field_patterns()
    analyze_data_types_and_constraints()
    analyze_sample_data_values()
    
    print(f"\n{'='*80}")
    print("ANALYSIS COMPLETE")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()
