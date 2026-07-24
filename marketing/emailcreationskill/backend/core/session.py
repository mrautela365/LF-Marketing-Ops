import uuid
from typing import Optional
from models import SessionState

_sessions: dict[str, SessionState] = {}


def create() -> SessionState:
    sid = str(uuid.uuid4())
    state = SessionState(session_id=sid)
    _sessions[sid] = state
    return state


def get(session_id: str) -> Optional[SessionState]:
    return _sessions.get(session_id)


def update(state: SessionState) -> None:
    _sessions[state.session_id] = state
