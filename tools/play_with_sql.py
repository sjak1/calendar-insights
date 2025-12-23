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
            WHERE LOWER(CUSTOMERNAME) LIKE 'hp'
            AND ROWNUM = 1
        """
        result = conn.execute(text(meeting_query))
        row = result.fetchone()
        print ("RESULT : ",result)
        print("ROW : ", row)














