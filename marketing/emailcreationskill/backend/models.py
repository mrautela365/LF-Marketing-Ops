from pydantic import BaseModel
from typing import Optional


class PlanRequest(BaseModel):
    url: str                          # Event/campaign URL — Claude extracts details from it
    extra_context: str | None = None  # Optional: anything user wants to add
    email_type: str | None = None       # HubSpot type: BATCH_EMAIL, LOCALTIME_EMAIL, AUTOMATED_EMAIL, etc.
    is_transactional: bool | None = None  # True = transactional (bypasses unsubscribe)
    progress_token: str | None = None  # optional: stream live "brief" of backend steps to /api/progress/{token}


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
    progress_token: str | None = None  # optional: stream live "brief" to /api/progress/{token}


class UpdateSectionsRequest(BaseModel):
    """Payload for POST /api/update-sections — user removed/reordered email content sections.
    Rebuilds the preview + body HTML from the trimmed sections and persists them on the session
    so the clone uses the edited content."""
    session_id: str
    sections: list = []  # ordered list of {type:'rich_text'|'button', ...} blocks to keep


class ChatRequest(BaseModel):
    session_id: str
    message: str  # Free-form follow-up message to Claude


class StagingBriefRequest(BaseModel):
    """
    Stateless request from the email-staging-v2/v3 skill.
    Bypasses the session-based UI flow — used only by the connected skill.
    Content priority: raw_html (doc) → event_url (AI generation) → none (settings only).
    """
    internal_token: str = ""              # must match INTERNAL_API_TOKEN in .env
    # Email identity
    clone_base_id: str
    email_name: str
    # Sender / audience settings
    from_name: str = ""
    from_address: str = ""
    subject: str = ""
    preview_text: str = ""
    email_type: str = "BATCH_EMAIL"
    send_list_id: str = ""
    suppression_list_ids: list[str] = []
    # Content — doc HTML wins; AI generation is the fallback when no doc
    raw_html: str = ""        # processed HTML from the Google Doc (Phase 2 of skill)
    event_url: str = ""       # fallback: generate content from this event URL
    # Event context used only with event_url AI generation
    event_name: str = ""
    event_dates: list[str] = []
    location: str = ""
    description: str = ""


class AsanaPlanRequest(BaseModel):
    """Payload for POST /api/plan-from-asana — fetches task and returns pre-filled brief."""
    asana_url: str


class AudiencePlanRequest(BaseModel):
    """Payload for POST /api/audience-plan — starts a segment planning job (Phase 1)."""
    session_id: str
    event_url: str = ""  # override; falls back to session's url_data if blank
    qa: str = ""         # optional user answers to clarifying questions (re-plan round)


class AudienceRunRequest(BaseModel):
    """Payload for POST /api/audience/run — standalone, no email session required."""
    event_url: str
    session_id: str = ""  # optional — if provided, master_list_id stored in session
    plan: str = ""        # optional — skip planning phase if provided
    qa: str = ""          # optional clarifying answers


class BuildAudienceRequest(BaseModel):
    """Payload for POST /api/build-audience — starts a list building job (Phase 2)."""
    session_id: str
    event_url: str = ""  # override; falls back to session's url_data if blank
    plan: str = ""       # segment plan output from Phase 1 (PLANNING_PROMPT)
    qa: str = ""         # optional user answers to clarifying questions


class CustomAudiencePlanRequest(BaseModel):
    """Payload for POST /api/audience/custom-plan — starts a Custom Request segment
    planning job (Phase 1). Free-form description instead of an event URL, e.g. a
    location combined with one or more named events for context."""
    request: str
    session_id: str = ""  # optional — if provided, master_list_id stored in session
    qa: str = ""          # optional user answers to clarifying questions (re-plan round)


class CustomAudienceRunRequest(BaseModel):
    """Payload for POST /api/audience/custom-run — builds the Custom Request
    audience list(s). Runs Phase 1+2 chained if plan is blank, Phase 2 only if
    plan text (from a prior /api/audience/custom-plan run) is supplied."""
    request: str
    session_id: str = ""  # optional — if provided, master_list_id stored in session
    plan: str = ""         # optional — skip planning phase if provided
    qa: str = ""           # optional clarifying answers


class SetSendListRequest(BaseModel):
    """Payload for POST /api/set-send-list — applies ONLY the send/suppression lists
    to an already-cloned email. Called explicitly after clone so the assignment is
    visible and verifiable, independent of the clone flow."""
    session_id: str = ""              # optional — resolves email_id + suppression from session
    email_id: str = ""                # optional — overrides session.email_id
    send_list_id: str = ""            # single-list form (back-compat) — one of send_list_id/send_list_ids required
    send_list_ids: list[str] = []     # plural form — 2+ lists reused directly from a prior send, no compose step
    suppression_list_ids: list[str] = []  # optional — falls back to session brand_history


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
