from local_db_main import query_engine

response = query_engine.query("What events are scheduled this month? ;(do not end the sql statement with a semi-colon)")
print(response); 
