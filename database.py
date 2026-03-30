"""
Shared database configuration and connection management.
"""

import os
from sqlalchemy import create_engine
from dotenv import load_dotenv

load_dotenv()

ORACLE_CONNECTION_URI = os.getenv("ORACLE_CONNECTION_URI")
if not ORACLE_CONNECTION_URI:
    raise ValueError("ORACLE_CONNECTION_URI environment variable is required")

# Create database engine once at module level (reused across calls)
engine = create_engine(ORACLE_CONNECTION_URI)
