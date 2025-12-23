"""
Session management for chat conversations.
"""
import uuid
from logging_config import get_logger

logger = get_logger(__name__)

# In-memory session storage: {session_id: [list of messages]}
# Each message is a dict with role and content
chat_sessions = {}


def get_or_create_session(session_id=None):
    """Get existing session or create a new one."""
    if session_id is None:
        session_id = str(uuid.uuid4())
        logger.info(f"Generated new session_id: {session_id}")
    
    # Initialize session if it doesn't exist
    if session_id not in chat_sessions:
        chat_sessions[session_id] = []
        logger.info(f"Created new chat session: {session_id}")
    
    return session_id


def get_session_history(session_id):
    """Get conversation history for a session."""
    return chat_sessions.get(session_id, [])


def add_to_session(session_id, user_message, assistant_message):
    """Add messages to session and trim if needed."""
    if session_id not in chat_sessions:
        chat_sessions[session_id] = []
    
    chat_sessions[session_id].append({"role": "user", "content": user_message})
    chat_sessions[session_id].append({"role": "assistant", "content": assistant_message})
    
    # Trim to last 20 messages (10 exchanges)
    if len(chat_sessions[session_id]) > 20:
        chat_sessions[session_id] = chat_sessions[session_id][-20:]
        logger.info(f"Trimmed conversation history for session {session_id}")
