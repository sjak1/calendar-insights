from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()


ORACLE_CONNECTION_URI = (
    "oracle+oracledb://BIQ_EIQ_AURORA:BIQ_EIQ_AURORA"
    "@biqdb.ciqohztp4uck.us-west-2.rds.amazonaws.com:1521/?service_name=ORCL"
)

engine = create_engine(ORACLE_CONNECTION_URI); 


with engine.connect() as conn:

        meeting_query = """
            SELECT 
                EVENTID,
                CUSTOMERNAME,
                CUSTOMERINDUSTRY,
                ACCOUNTTYPE,
                LINEOFBUSINESS,
                VISITFOCUS,
                MEETINGOBJECTIVE,
                SALESPLAY,
                PILLARS,
                FORMTYPE,
                REGION,
                TIER
            FROM VW_OPERATIONS_REPORT 
            WHERE LOWER(CUSTOMERNAME) LIKE '%humana%'
            AND ROWNUM = 1
        """
        result = conn.execute(text(meeting_query))
        row = result.fetchone()
        print ("RESULT : ",result)
        print("ROW : ", row)

        if row: 
            actual_company = row[1]
            actual_event_id = row[0]
            print(f"Actual company: {actual_company}")  
            print(f"Actual event_id: {actual_event_id}")
        else:
            print("No row found")
            exit() 

        attendee_query = f"""
            SELECT 
                FIRSTNAME || ' ' || LASTNAME as full_name,
                BUSINESSTITLE,
                CHIEFOFFICERTITLE,
                DECISIONMAKER,
                INFLUENCER,
                ISTECHNICAL,
                ATTENDEETYPE,
                ISREMOTE
            FROM VW_ATTENDEE_REPORT 
            WHERE EVENTID = '{actual_event_id}'
        """
        print(f"Querying attendees for event_id: {actual_event_id}")
        print(f"Query: {attendee_query}")
        result = conn.execute(text(attendee_query))
        attendee_rows = result.fetchall()
        print(f"\nFound {len(attendee_rows)} attendees:")
        print("=" * 80)
        for i, attendee_row in enumerate(attendee_rows, 1):
            print(f"\nAttendee {i}:")
            print(f"  Name: {attendee_row[0]}")
            print(f"  Title: {attendee_row[1]}")
            print(f"  C-Level: {attendee_row[2]}")
            print(f"  Decision Maker: {attendee_row[3]}")
            print(f"  Influencer: {attendee_row[4]}")
            print(f"  Technical: {attendee_row[5]}")
            print(f"  Type: {attendee_row[6]}")
            print(f"  Remote: {attendee_row[7]}")
        
        actual_company = row[1]
        print(f"Actual company: {actual_company}")

        
        previous_meeting_query = f"""
            SELECT 
                EVENTID,
                TO_CHAR(DATE '1970-01-01' + (STARTDATEMS/1000)/86400, 'YYYY-MM-DD') as meeting_date,
                VISITFOCUS,
                SALESPLAY,
                PILLARS,
                MEETINGOBJECTIVE
            FROM VW_OPERATIONS_REPORT 
            WHERE CUSTOMERNAME = '{actual_company}'
            AND EVENTID != '{actual_event_id}'
            ORDER BY meeting_date DESC
            FETCH FIRST 5 ROWS ONLY
        """
        print(f"Querying previous meetings for company: {actual_company}")
        print(f"Query: {previous_meeting_query}")
        result = conn.execute(text(previous_meeting_query))
        rows = result.fetchall()
        print(f"Found {len(rows)} previous meetings")
        for row, index in enumerate(rows, 1):
            print(f"Previous meeting {index}: {row}")

    