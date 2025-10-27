from sqlalchemy import (
    create_engine,
    MetaData,
    inspect,
    text
)
import pandas as pd

# Database connection setup
engine = create_engine("oracle+oracledb://BIQ_EIQ_AURORA:BIQ_EIQ_AURORA@biqdb.ciqohztp4uck.us-west-2.rds.amazonaws.com:1521/?service_name=ORCL")
meta = MetaData()

# Tables from local_db_main.py
TABLES_TO_ANALYZE = [
    "t_request_opportunity",
    "t_request_agenda_presenter", 
    "t_request_agenda_details",
    "t_request_agenda",
    "m_user_role",
    "t_event_activity_day",
    "m_request_master"
]

def analyze_table_structure(table_name):
    """Analyze the structure of a specific table"""
    print(f"\n{'='*80}")
    print(f"ANALYZING TABLE: {table_name.upper()}")
    print(f"{'='*80}")
    
    try:
        # Get table metadata
        meta.reflect(bind=engine, only=[table_name])
        table = meta.tables[table_name]
        
        print(f"Table Name: {table.name}")
        print(f"Schema: {table.schema}")
        
        # Column information
        print(f"\nCOLUMNS ({len(table.columns)}):")
        print("-" * 60)
        for column in table.columns:
            nullable = "NULL" if column.nullable else "NOT NULL"
            default = f"DEFAULT {column.default}" if column.default else ""
            print(f"  {column.name:<30} {str(column.type):<20} {nullable:<10} {default}")
        
        # Primary keys
        if table.primary_key:
            pk_columns = [col.name for col in table.primary_key.columns]
            print(f"\nPRIMARY KEY: {', '.join(pk_columns)}")
        
        # Foreign keys
        if table.foreign_keys:
            print(f"\nFOREIGN KEYS:")
            for fk in table.foreign_keys:
                print(f"  {fk.parent.name} -> {fk.target_fullname}")
        
        # Get row count
        with engine.connect() as conn:
            result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            row_count = result.scalar()
            print(f"\nROW COUNT: {row_count:,}")
        
        # Get sample data (first 3 rows)
        print(f"\nSAMPLE DATA (first 3 rows):")
        print("-" * 60)
        with engine.connect() as conn:
            result = conn.execute(text(f"SELECT * FROM {table_name} WHERE ROWNUM <= 3"))
            columns = result.keys()
            rows = result.fetchall()
            
            if rows:
                # Print column headers
                header = " | ".join([col[:15].ljust(15) for col in columns])
                print(header)
                print("-" * len(header))
                
                # Print rows
                for row in rows:
                    row_str = " | ".join([str(val)[:15].ljust(15) if val is not None else "NULL".ljust(15) for val in row])
                    print(row_str)
            else:
                print("  No data found")
                
    except Exception as e:
        print(f"Error analyzing table {table_name}: {str(e)}")

def analyze_table_relationships():
    """Analyze relationships between tables"""
    print(f"\n{'='*80}")
    print("TABLE RELATIONSHIPS")
    print(f"{'='*80}")
    
    meta.reflect(bind=engine, only=TABLES_TO_ANALYZE)
    
    for table_name in TABLES_TO_ANALYZE:
        if table_name in meta.tables:
            table = meta.tables[table_name]
            
            # Check for foreign keys to other tables in our list
            related_tables = set()
            for fk in table.foreign_keys:
                target_table = fk.target_fullname.split('.')[0].lower()
                if target_table in TABLES_TO_ANALYZE:
                    related_tables.add(target_table)
            
            if related_tables:
                print(f"\n{table_name.upper()} references:")
                for related_table in related_tables:
                    print(f"  -> {related_table}")
            else:
                print(f"\n{table_name.upper()}: No direct references to other tables in our list")

def get_table_summary():
    """Get a summary of all tables"""
    print(f"\n{'='*80}")
    print("TABLE SUMMARY")
    print(f"{'='*80}")
    
    summary_data = []
    
    for table_name in TABLES_TO_ANALYZE:
        try:
            with engine.connect() as conn:
                # Get row count
                result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                row_count = result.scalar()
                
                # Get column count
                meta.reflect(bind=engine, only=[table_name])
                if table_name in meta.tables:
                    column_count = len(meta.tables[table_name].columns)
                    
                    summary_data.append({
                        'Table': table_name,
                        'Columns': column_count,
                        'Rows': f"{row_count:,}",
                        'Status': '✓ Available'
                    })
                else:
                    summary_data.append({
                        'Table': table_name,
                        'Columns': 'N/A',
                        'Rows': 'N/A',
                        'Status': '✗ Not Found'
                    })
                    
        except Exception as e:
            summary_data.append({
                'Table': table_name,
                'Columns': 'N/A',
                'Rows': 'N/A',
                'Status': f'✗ Error: {str(e)[:30]}...'
            })
    
    # Display summary table
    df = pd.DataFrame(summary_data)
    print(df.to_string(index=False))

def main():
    """Main function to run the analysis"""
    print("SQLAlchemy Table Analysis")
    print("=" * 80)
    print(f"Analyzing {len(TABLES_TO_ANALYZE)} tables from local_db_main.py")
    
    # Test connection
    try:
        with engine.connect() as conn:
            print("✓ Database connection successful")
    except Exception as e:
        print(f"✗ Database connection failed: {str(e)}")
        return
    
    # Get summary first
    get_table_summary()
    
    # Analyze relationships
    analyze_table_relationships()
    
    # Analyze each table in detail
    for table_name in TABLES_TO_ANALYZE:
        analyze_table_structure(table_name)
    
    print(f"\n{'='*80}")
    print("ANALYSIS COMPLETE")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()
