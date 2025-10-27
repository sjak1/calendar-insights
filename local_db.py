from sqlalchemy import (
    create_engine,
    MetaData,
    Table,
    Column,
    String,
    Integer,
    select,
    inspect,
)


engine = create_engine("oracle+oracledb://BIQ_EIQ_AURORA:BIQ_EIQ_AURORA@biqdb.ciqohztp4uck.us-west-2.rds.amazonaws.com:1521/?service_name=ORCL")
meta = MetaData()
meta.reflect(bind=engine)

my_table = meta.tables['t_location_calendar']

with engine.connect() as conn:
    print("meta table keys here :: ")
    print(meta.tables.keys())
    rows = conn.execute(my_table.select()).fetchall()
    print(rows)

#insp = inspect(engine)
#print(insp.get_table_names(schema='BIQ_EIQ_AURORA'))  # choose the correct name from this list

