"""
JSON utility functions.
"""
import json
from datetime import datetime, date


def json_dumps_safe(obj):
    """
    Safely serialize objects to JSON, converting datetime and date objects to ISO format strings.
    Handles datetime/date objects and other non-serializable types that may come from database queries.
    """
    def default_serializer(o):
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        # Try to use model_dump if it's a Pydantic model
        if hasattr(o, 'model_dump'):
            return o.model_dump()
        # Try to convert to dict if it has __dict__
        if hasattr(o, '__dict__'):
            return o.__dict__
        # Handle other non-serializable types
        return str(o)
    
    return json.dumps(obj, default=default_serializer)
