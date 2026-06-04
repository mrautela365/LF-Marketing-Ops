from pydantic import BaseModel
from typing import Optional, Any


class EmailRequest(BaseModel):
    brand: str
    asana_task_url: Optional[str] = None
    subject: Optional[str] = None
    preview_text: Optional[str] = None
    content_url: Optional[str] = None
    content_html: Optional[str] = None
    send_date: Optional[str] = None
    audience: Optional[str] = None
    from_name: Optional[str] = None
    from_address: Optional[str] = None


class ContinueRequest(BaseModel):
    answer: str


class QAItem(BaseModel):
    item: str
    passed: bool
    note: Optional[str] = None


class EmailSummary(BaseModel):
    subject: Optional[str] = None
    from_: Optional[str] = None
    send_list: Optional[str] = None
    suppressions: list[str] = []
    email_type: Optional[str] = None
    status: str = "DRAFT"


class AgentResponse(BaseModel):
    session_id: str
    status: str  # "complete" | "needs_input" | "error"
    question: Optional[str] = None
    email_id: Optional[str] = None
    email_name: Optional[str] = None
    hubspot_url: Optional[str] = None
    summary: Optional[EmailSummary] = None
    qa_checklist: Optional[list[QAItem]] = None
    error: Optional[str] = None
