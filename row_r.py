from db_init import engine, city_stats_table
from use_db import sql_database,llm
from llama_index.core.schema import TextNode

with engine.connect() as connection:
    results = connection.execute(stmt).fetchall()

city_nodes = [TextNode(text=str(t)) for t in results]

city_rows_index = VectorStoreIndex(
    city_nodes, embed_model=OpenAIEmbedding(model="text-embedding-3-small")
)
city_rows_retriever = city_rows_index.as_retriever(similarity_top_k=1)

city_rows_retriever.retrieve("US")

rows_retrievers = {
    "city_stats": city_rows_retriever,
}
query_engine = SQLTableRetrieverQueryEngine(
    sql_database,
    obj_index.as_retriever(similarity_top_k=1),
    rows_retrievers=rows_retrievers,
)
