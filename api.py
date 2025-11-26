from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from get_gdp import handle_query
from pydantic import BaseModel
import os
from logging_config import setup_logging, get_logger

# Setup logging for FastAPI
setup_logging()
logger = get_logger(__name__)

app = FastAPI()

# Mount static files directory
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

class QueryPayload(BaseModel):
    query: str
    headers: dict

@app.get("/")
async def root():
    """Serve the UI"""
    logger.info("Root endpoint accessed")
    static_file = os.path.join(static_dir, "index.html")
    if os.path.exists(static_file):
        return FileResponse(static_file)
    return {"message": "BriefingIQ AI Assistant API", "endpoints": {"/process_query": "POST"}}

@app.post("/process_query")
async def process_query(payload: QueryPayload):
    query = payload.query
    headers = payload.headers
    logger.info(f"Processing query: {query[:100]}...")  # Log first 100 chars
    try:
        result = handle_query(query, headers)
        logger.info("Query processed successfully")
        return {"message": result}
    except Exception as e:
        logger.error(f"Error processing query: {e}", exc_info=True)
        raise
