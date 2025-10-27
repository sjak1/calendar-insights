from sqlalchemy import create_engine, text

# Database connection
engine = create_engine("oracle+oracledb://BIQ_EIQ_AURORA:BIQ_EIQ_AURORA@biqdb.ciqohztp4uck.us-west-2.rds.amazonaws.com:1521/?service_name=ORCL")

def analyze_master_table_fields():
    """Analyze what's actually in the custom fields of M_REQUEST_MASTER"""
    print("M_REQUEST_MASTER - CUSTOM FIELD ANALYSIS")
    print("=" * 60)
    
    # Check which custom fields have data
    query = """
    SELECT 
        COUNT(*) as total_rows,
        COUNT(text_field_1) as tf1_count,
        COUNT(text_field_2) as tf2_count,
        COUNT(text_field_3) as tf3_count,
        COUNT(text_field_4) as tf4_count,
        COUNT(text_field_5) as tf5_count,
        COUNT(text_field_6) as tf6_count,
        COUNT(text_field_7) as tf7_count,
        COUNT(text_field_8) as tf8_count,
        COUNT(text_field_9) as tf9_count,
        COUNT(text_field_10) as tf10_count,
        COUNT(text_field_11) as tf11_count,
        COUNT(date_field_1) as df1_count,
        COUNT(date_field_2) as df2_count,
        COUNT(date_field_3) as df3_count,
        COUNT(date_field_4) as df4_count,
        COUNT(date_field_5) as df5_count,
        COUNT(number_field_1) as nf1_count,
        COUNT(number_field_2) as nf2_count,
        COUNT(number_field_3) as nf3_count,
        COUNT(number_field_4) as nf4_count,
        COUNT(number_field_5) as nf5_count,
        COUNT(boolean_field_1) as bf1_count,
        COUNT(boolean_field_2) as bf2_count,
        COUNT(boolean_field_3) as bf3_count,
        COUNT(boolean_field_4) as bf4_count,
        COUNT(boolean_field_5) as bf5_count,
        COUNT(text_area_field_1) as taf1_count,
        COUNT(text_area_field_2) as taf2_count,
        COUNT(text_area_field_3) as taf3_count,
        COUNT(text_area_field_4) as taf4_count,
        COUNT(text_area_field_5) as taf5_count
    FROM m_request_master
    """
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query))
            row = result.fetchone()
            
            print(f"Total rows: {row[0]}")
            print("\nTEXT FIELDS (how many have data):")
            text_fields = [
                ('text_field_1', row[2]), ('text_field_2', row[3]), ('text_field_3', row[4]),
                ('text_field_4', row[5]), ('text_field_5', row[6]), ('text_field_6', row[7]),
                ('text_field_7', row[8]), ('text_field_8', row[9]), ('text_field_9', row[10]),
                ('text_field_10', row[11]), ('text_field_11', row[12])
            ]
            
            for field, count in text_fields:
                if count > 0:
                    print(f"  {field}: {count} rows have data")
            
            print("\nDATE FIELDS:")
            date_fields = [
                ('date_field_1', row[13]), ('date_field_2', row[14]), ('date_field_3', row[15]),
                ('date_field_4', row[16]), ('date_field_5', row[17])
            ]
            
            for field, count in date_fields:
                if count > 0:
                    print(f"  {field}: {count} rows have data")
            
            print("\nNUMBER FIELDS:")
            number_fields = [
                ('number_field_1', row[18]), ('number_field_2', row[19]), ('number_field_3', row[20]),
                ('number_field_4', row[21]), ('number_field_5', row[22])
            ]
            
            for field, count in number_fields:
                if count > 0:
                    print(f"  {field}: {count} rows have data")
            
            print("\nBOOLEAN FIELDS:")
            boolean_fields = [
                ('boolean_field_1', row[23]), ('boolean_field_2', row[24]), ('boolean_field_3', row[25]),
                ('boolean_field_4', row[26]), ('boolean_field_5', row[27])
            ]
            
            for field, count in boolean_fields:
                if count > 0:
                    print(f"  {field}: {count} rows have data")
            
            print("\nTEXT AREA FIELDS:")
            text_area_fields = [
                ('text_area_field_1', row[28]), ('text_area_field_2', row[29]), ('text_area_field_3', row[30]),
                ('text_area_field_4', row[31]), ('text_area_field_5', row[32])
            ]
            
            for field, count in text_area_fields:
                if count > 0:
                    print(f"  {field}: {count} rows have data")
                    
    except Exception as e:
        print(f"Error: {str(e)}")

def get_sample_custom_field_data():
    """Get sample data from custom fields that have data"""
    print("\n\nSAMPLE DATA FROM CUSTOM FIELDS")
    print("=" * 60)
    
    # Get sample data from fields that have data
    query = """
    SELECT 
        id,
        event_name,
        text_field_1, text_field_2, text_field_3, text_field_4, text_field_5,
        date_field_1, date_field_2, date_field_3,
        number_field_1, number_field_2, number_field_3,
        boolean_field_1, boolean_field_2,
        text_area_field_1, text_area_field_2
    FROM m_request_master
    WHERE (text_field_1 IS NOT NULL OR text_field_2 IS NOT NULL OR text_field_3 IS NOT NULL 
           OR text_field_4 IS NOT NULL OR text_field_5 IS NOT NULL
           OR date_field_1 IS NOT NULL OR date_field_2 IS NOT NULL OR date_field_3 IS NOT NULL
           OR number_field_1 IS NOT NULL OR number_field_2 IS NOT NULL OR number_field_3 IS NOT NULL
           OR boolean_field_1 IS NOT NULL OR boolean_field_2 IS NOT NULL
           OR text_area_field_1 IS NOT NULL OR text_area_field_2 IS NOT NULL)
    AND ROWNUM <= 5
    """
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query))
            rows = result.fetchall()
            columns = result.keys()
            
            if rows:
                print("Sample records with custom field data:")
                print("-" * 80)
                
                for i, row in enumerate(rows, 1):
                    print(f"\nRecord {i} (ID: {row[0]}, Event: {row[1]}):")
                    
                    # Check text fields
                    text_fields = ['text_field_1', 'text_field_2', 'text_field_3', 'text_field_4', 'text_field_5']
                    for j, field in enumerate(text_fields, 2):
                        if row[j] is not None:
                            print(f"  {field}: {row[j]}")
                    
                    # Check date fields
                    date_fields = ['date_field_1', 'date_field_2', 'date_field_3']
                    for j, field in enumerate(date_fields, 7):
                        if row[j] is not None:
                            print(f"  {field}: {row[j]}")
                    
                    # Check number fields
                    number_fields = ['number_field_1', 'number_field_2', 'number_field_3']
                    for j, field in enumerate(number_fields, 10):
                        if row[j] is not None:
                            print(f"  {field}: {row[j]}")
                    
                    # Check boolean fields
                    boolean_fields = ['boolean_field_1', 'boolean_field_2']
                    for j, field in enumerate(boolean_fields, 13):
                        if row[j] is not None:
                            print(f"  {field}: {row[j]}")
                    
                    # Check text area fields
                    text_area_fields = ['text_area_field_1', 'text_area_field_2']
                    for j, field in enumerate(text_area_fields, 15):
                        if row[j] is not None:
                            print(f"  {field}: {str(row[j])[:100]}...")
            else:
                print("No records found with custom field data")
                
    except Exception as e:
        print(f"Error: {str(e)}")

def analyze_core_master_fields():
    """Analyze the core business fields in M_REQUEST_MASTER"""
    print("\n\nCORE BUSINESS FIELDS IN M_REQUEST_MASTER")
    print("=" * 60)
    
    query = """
    SELECT 
        event_name,
        event_format,
        status,
        poc,
        city,
        email,
        requester_email,
        dress_code,
        gift_type,
        duration,
        category_type_id,
        category_id,
        location_id,
        l_start_date,
        end_date,
        timezone_id,
        tenant_id,
        notes,
        technical_requirements
    FROM m_request_master
    WHERE ROWNUM <= 10
    """
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query))
            rows = result.fetchall()
            
            if rows:
                print("Sample core business data:")
                print("-" * 80)
                
                for i, row in enumerate(rows, 1):
                    print(f"\nEvent {i}:")
                    print(f"  Name: {row[0]}")
                    print(f"  Format: {row[1]}")
                    print(f"  Status: {row[2]}")
                    print(f"  POC: {row[3]}")
                    print(f"  City: {row[4]}")
                    print(f"  Email: {row[5]}")
                    print(f"  Requester: {row[6]}")
                    print(f"  Dress Code: {row[7]}")
                    print(f"  Gift Type: {row[8]}")
                    print(f"  Duration: {row[9]} days")
                    print(f"  Category Type: {row[10]}")
                    print(f"  Category: {row[11]}")
                    print(f"  Location: {row[12]}")
                    print(f"  Start Date: {row[13]}")
                    print(f"  End Date: {row[14]}")
                    print(f"  Timezone: {row[15]}")
                    print(f"  Tenant: {row[16]}")
                    if row[17]:  # notes
                        print(f"  Notes: {str(row[17])[:100]}...")
                    if row[18]:  # technical_requirements
                        print(f"  Technical: {str(row[18])[:100]}...")
                        
    except Exception as e:
        print(f"Error: {str(e)}")

def main():
    """Main analysis function"""
    print("SIMPLE FIELD ANALYSIS")
    print("=" * 60)
    
    try:
        with engine.connect() as conn:
            print("✓ Database connection successful")
    except Exception as e:
        print(f"✗ Database connection failed: {str(e)}")
        return
    
    analyze_master_table_fields()
    get_sample_custom_field_data()
    analyze_core_master_fields()
    
    print(f"\n{'='*60}")
    print("ANALYSIS COMPLETE")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
