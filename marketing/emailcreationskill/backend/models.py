from pydantic import BaseModel
from typing import Optional


class PlanRequest(BaseModel):
    url: str                          # Event/campaign URL — Claude extracts details from it
    extra_context: str | None = None  # Optional: anything user wants to add
    email_type: str | None = None       # HubSpot type: BATCH_EMAIL, LOCALTIME_EMAIL, AUTOMATED_EMAIL, etc.
    is_transactional: bool | None = None  # True = transactional (bypasses unsubscribe)


class CloneRequest(BaseModel):
    session_id: str
    approved: bool
    subject: Optional[str] = None
    preview_text: Optional[str] = None
    send_list_id: Optional[str] = None


class ContentRequest(BaseModel):
    session_id: str
    content: str  # Google Doc URL or raw HTML or plain text


class GenerateContentRequest(BaseModel):
    session_id: str
    change_request: str | None = None  # optional: "make subject shorter", "more urgent tone", etc.


class ChatRequest(BaseModel):
    session_id: str
    message: str  # Free-form follow-up message to Claude


class SessionState(BaseModel):
    session_id: str
    phase: str = "planning"  # planning | cloned | complete
    plan: Optional[dict] = None
    email_id: Optional[str] = None
    draft_url: Optional[str] = None
    messages: list = []
    meta: dict = {}  # Direct-mode state (brand history, email name, etc.)

    class Config:
        arbitrary_types_allowed = True
