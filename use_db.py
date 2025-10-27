from llama_index.core import SQLDatabase
from llama_index.llms.openai import OpenAI
from sqlalchemy import insert, select
from db_init import engine, city_stats_table
from dotenv import load_dotenv

load_dotenv()

llm = OpenAI(temperature=0.1, model="gpt-4.1-mini")
sql_database = SQLDatabase(engine, include_tables=["city_stats"])

rows = [
    {"city_name": "Toronto", "population": 2930000, "country": "Canada"},
    {"city_name": "Tokyo", "population": 13960000, "country": "Japan"},
    {
        "city_name": "Chicago",
        "population": 2679000,
        "country": "United States",
    },
    {
        "city_name": "New York",
        "population": 8258000,
        "country": "United States",
    },
    {"city_name": "Seoul", "population": 9776000, "country": "South Korea"},
    {"city_name": "Busan", "population": 3334000, "country": "South Korea"},
]

for row in rows:
    stmt = insert(city_stats_table).values(**row)
    with engine.begin() as connection:
        cursor = connection.execute(stmt)


stmt = select(
    city_stats_table.c.city_name,
    city_stats_table.c.population,
    city_stats_table.c.country,
).select_from(city_stats_table)

with engine.connect() as connection:
    results = connection.execute(stmt).fetchall()
    print(results)
