"""
Upload Dell EBD to database.

This script:
1. Queries the DB for Dell's event_id (from VW_OPERATIONS_REPORT)
2. Reads the local Dell EBD PDF (documents/ebd/EBD_Dell_Unstructured.pdf)
3. Inserts into VW_EVENT_DOCUMENT_REPORT for that event

Run: python seed/upload_dell_ebd_to_db.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sqlalchemy import create_engine, text

# DB connection (same as agenda_generator)
ORACLE_CONNECTION_URI = os.getenv(
    "ORACLE_CONNECTION_URI",
    "oracle+oracledb://BIQ_EIQ_AURORA:BIQ_EIQ_AURORA"
    "@biqdb.ciqohztp4uck.us-west-2.rds.amazonaws.com:1521/?service_name=ORCL",
)

# Tables for VW_EVENT_DOCUMENT_REPORT
# The view is built on T_UPLOAD_HEADER (linked to event via OWNER_ID) and T_UPLOAD_LINE (has the document)
UPLOAD_HEADER_TABLE = "T_UPLOAD_HEADER"
UPLOAD_LINE_TABLE = "T_UPLOAD_LINE"

# Must match values in view (not the BI_REQUEST_DOCUMENTS table)
DOCUMENT_CATEGORY = "Executive Briefing Document"

# Dell EBD file path
DELL_EBD_PATH = Path(__file__).parent.parent / "documents" / "ebd" / "EBD_Dell_Unstructured.pdf"


def find_dell_event():
    """Find Dell's event_id from VW_OPERATIONS_REPORT."""
    engine = create_engine(ORACLE_CONNECTION_URI)
    
    # Try different patterns for Dell
    patterns = ['%Dell%', '%DELL%', '%dell%']
    
    with engine.connect() as conn:
        for pattern in patterns:
            query = text("""
                SELECT EVENTID, CUSTOMERNAME
                FROM VW_OPERATIONS_REPORT
                WHERE UPPER(CUSTOMERNAME) LIKE UPPER(:pattern)
                FETCH FIRST 5 ROW ONLY
            """)
            result = conn.execute(query, {"pattern": pattern})
            rows = result.fetchall()
            
            if rows:
                print(f"Found {len(rows)} Dell event(s):")
                for i, row in enumerate(rows):
                    print(f"  {i+1}. {row[1]} (ID: {row[0]})")
                return rows
    
    return None


def check_existing_ebd(event_id):
    """Check if Dell already has an EBD in VW_EVENT_DOCUMENT_REPORT."""
    engine = create_engine(ORACLE_CONNECTION_URI)
    
    with engine.connect() as conn:
        query = text("""
            SELECT eventid, file_name, file_size, document_category
            FROM VW_EVENT_DOCUMENT_REPORT
            WHERE eventid = :event_id
            AND document_category = :doc_cat
        """)
        result = conn.execute(query, {"event_id": event_id, "doc_cat": DOCUMENT_CATEGORY})
        row = result.fetchone()
        return row


def upload_dell_ebd(event_id):
    """Upload Dell EBD PDF to the database.
    
    Uses BI_REQUEST_DOCUMENTS table with columns:
    - REQUEST_ID: The event/request ID
    - DOCUMENT: BLOB of the PDF
    - DOCUMENT_NAME: File name
    - DOCUMENT_CONTENT_TYPE: MIME type
    - DOCUMENT_SIZE: File size in bytes
    - DOCUMENT_TYPE: Category (e.g., 'Executive Briefing Document')
    - IS_ACTIVE: '1' for active
    """
    
    if not DELL_EBD_PATH.exists():
        print(f"Error: Dell EBD file not found: {DELL_EBD_PATH}")
        sys.exit(1)
    
    with open(DELL_EBD_PATH, "rb") as f:
        doc_bytes = f.read()
    
    file_name = DELL_EBD_PATH.name
    content_type = "application/pdf"
    file_size = len(doc_bytes)
    
    engine = create_engine(ORACLE_CONNECTION_URI)
    
    # Insert into BI_REQUEST_DOCUMENTS
    # ID is required and not auto-generated; use MAX(ID) + 1
    sql = text(f"""
        INSERT INTO {EBD_INSERT_TABLE} (
            ID,
            REQUEST_ID, 
            DOCUMENT, 
            DOCUMENT_NAME, 
            DOCUMENT_CONTENT_TYPE, 
            DOCUMENT_SIZE, 
            DOCUMENT_TYPE,
            IS_ACTIVE,
            CREATED_BY,
            CREATED_TS
        )
        VALUES (
            (SELECT NVL(MAX(ID), 0) + 1 FROM {EBD_INSERT_TABLE}),
            :request_id, 
            :document, 
            :document_name, 
            :document_content_type, 
            :document_size, 
            :document_type,
            '1',
            'AI_SEED_SCRIPT',
            CURRENT_TIMESTAMP
        )
    """)
    
    try:
        with engine.begin() as conn:
            conn.execute(sql, {
                "request_id": int(event_id),
                "document": doc_bytes,
                "document_name": file_name,
                "document_content_type": content_type,
                "document_size": file_size,
                "document_type": DOCUMENT_CATEGORY,
            })
        print(f"\n✅ Uploaded Dell EBD to {EBD_INSERT_TABLE}")
        print(f"   request_id: {event_id}")
        print(f"   file: {file_name} ({file_size} bytes)")
        print(f"\nVerify: SELECT * FROM VW_EVENT_DOCUMENT_REPORT WHERE eventid = '{event_id}';")
        return True
    except Exception as e:
        print(f"\n❌ Upload failed: {e}")
        print("\nPossible issues:")
        print("  - Missing ID column (may need sequence)")
        print("  - Missing TENANT_ID or other required columns")
        print("  - Insufficient permissions")
        return False


def main():
    print("=" * 60)
    print("Dell EBD Upload Script")
    print("=" * 60)
    
    # Step 1: Find Dell events
    print("\n📋 Searching for Dell events in database...")
    dell_events = find_dell_event()
    
    if not dell_events:
        print("❌ No Dell events found in VW_OPERATIONS_REPORT.")
        print("   Make sure Dell has events in the system.")
        sys.exit(1)
    
    # Use the first (most recent) Dell event
    event_id = str(dell_events[0][0])
    customer_name = dell_events[0][1]
    
    print(f"\n🎯 Using event: {customer_name} (ID: {event_id})")
    
    # Step 2: Check if EBD already exists
    print("\n🔍 Checking for existing EBD...")
    existing = check_existing_ebd(event_id)
    if existing:
        print(f"⚠️  Dell already has an EBD: {existing[1]} ({existing[2]} bytes)")
        response = input("   Overwrite? (y/N): ").strip().lower()
        if response != 'y':
            print("   Aborted.")
            sys.exit(0)
    else:
        print("   No existing EBD found for this event.")
    
    # Step 3: Upload
    print(f"\n📤 Uploading {DELL_EBD_PATH.name}...")
    upload_dell_ebd(event_id)


if __name__ == "__main__":
    main()
