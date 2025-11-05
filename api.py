from fastapi import FastAPI
from get_gdp import handle_query
from pydantic import BaseModel
app = FastAPI()

class QueryPayload(BaseModel):
    query: str
    headers: dict

@app.get("/")
async def root():
    return {"messages": "Hello World"}

@app.post("/process_query")
async def process_query(payload: QueryPayload):
    query = payload.query
    headers = payload.headers
    result = handle_query(query, headers)
    return {"message": result}
