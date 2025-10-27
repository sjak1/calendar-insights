from llama_index.core.indices.struct_store.sql_query import (
    SQLTableRetrieverQueryEngine,
) 

from llama_index.core.objects import (
    SQLTableNodeMapping,
    ObjectIndex,
    SQLTableSchema
)

from llama_index.core import VectorStoreIndex
from llama_index.embeddings.openai import OpenAIEmbedding
from use_db import sql_database,llm
from dotenv import load_dotenv

load_dotenv()

city_stats_text = (
    "This table gives information regarding the population and country of a"
    " given city.\nThe user will query with codewords, where 'loo' corresponds"
    " to population and 'bar'corresponds to city."
)

table_node_mapping1 = SQLTableNodeMapping(sql_database)
table_schema_objs1 = [
    (SQLTableSchema(table_name="city_stats", context_str=city_stats_text))
]

obj_index1 = ObjectIndex.from_objects(
    table_schema_objs1,
    table_node_mapping1,
    VectorStoreIndex,
    embed_model=OpenAIEmbedding(model="text-embedding-3-small"),
)
query_engine1 = SQLTableRetrieverQueryEngine(
    sql_database, obj_index1.as_retriever(similarity_top_k=1), verbose=True
)

response = query_engine1.query("Which bar has the highest loo?")
print(response)
