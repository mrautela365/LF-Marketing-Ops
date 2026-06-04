import uuid
from typing import Optional


_sessions: dict[str, dict] = {}


def create_session(request_data: dict = None) -> str:
    session_id = str(uuid.uuid4())
    _sessions[session_id] = {
        "session_id": session_id,
        "messages": [],
        "email_id": None,
        "status": "in_progress",
        "request_data": request_data or {},  # raw request fields, updated as user answers questions
    }
    return session_id


def get_session(session_id: str) -> Optional[dict]:
    return _sessions.get(session_id)


def update_session(session_id: str, **kwargs) -> None:
    if session_id in _sessions:
        _sessions[session_id].update(kwargs)


def append_message(session_id: str, role: str, content) -> None:
    if session_id in _sessions:
        _sessions[session_id]["messages"].append({"role": role, "content": content})
