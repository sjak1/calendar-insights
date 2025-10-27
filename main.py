from llama_index.core.query_engine import NLSQLTableQueryEngine
from db_init import engine, city_stats_table
from use_db import sql_database,llm
import os

query_engine = NLSQLTableQueryEngine(
    sql_database=sql_database, tables=["city_stats"], llm=llm
)

query_str = "which of these cities have highest and lowest populations respectively?"
response = query_engine.query(query_str)

print(response)
