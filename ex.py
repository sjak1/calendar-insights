from sqlalchemy import create_engine, text

engine = create_engine("oracle+oracledb://BIQ_EIQ_AURORA:BIQ_EIQ_AURORA@biqdb.ciqohztp4uck.us-west-2.rds.amazonaws.com:1521/?service_name=ORCL")

with engine.connect() as conn:
    result = conn.execute(
        text("SELECT * FROM user_tab_comments WHERE table_name = 'M_REPORT_PARAM_MAPPING'")
    )
    columns = [row[0] for row in result]
    print(columns)

