from typing import Optional, Literal
from pydantic import BaseModel


class GeneratePreviewRequest(BaseModel):
    source_text: str
    promoted_url: str
    email_type: Literal["survey", "report"]
    email_plan: Literal["single", "sequence"] = "single"
    hero_image_id: Optional[str] = ""


class VariantContent(BaseModel):
    """One email's editable copy. stage is "single" for a one-off email, or
    "invite" / "reminder" / "deadline" for a 3-email lifecycle sequence."""
    stage: str = "single"
    subject: str
    preview_text: str
    hero_headline: str
    body_paragraphs: list
    use_bullets: bool = False
    bullets: list = []
    incentive: str = ""
    impact_sentence: str = ""
    share_line: str = ""
    cta_text: str = ""


class VariantPreview(VariantContent):
    hero_image_url: str = ""
    html: str


class GeneratePreviewResponse(BaseModel):
    email_type: Literal["survey", "report"]
    email_plan: Literal["single", "sequence"]
    variants: list[VariantPreview]


class RerenderPreviewRequest(BaseModel):
    email_type: Literal["survey", "report"]
    promoted_url: str
    hero_image_id: Optional[str] = ""
    variant: VariantContent


class RerenderPreviewResponse(BaseModel):
    stage: str
    html: str
    hero_image_url: str = ""


class UploadHeroImageResponse(BaseModel):
    hero_image_id: str
    url: str


class ApproveRequest(BaseModel):
    email_type: Literal["survey", "report"]
    promoted_url: str
    hero_image_id: Optional[str] = ""
    variants: list[VariantContent]


class ApproveResultItem(BaseModel):
    stage: str
    email_id: str
    draft_url: str
    state: str
    cloned_from_name: str


class ApproveResponse(BaseModel):
    results: list[ApproveResultItem]
    warnings: list[str] = []


# --- Audience Preview (custom audience builder) ---

class AudienceLocation(BaseModel):
    city: str
    country: Optional[str] = ""


class OpenQuestion(BaseModel):
    question: str
    why_it_blocks: str = ""
    options: list = []


class AudiencePlan(BaseModel):
    """Structured plan the LLM proposes from a free-text audience description.
    A real schema instead of round-tripped prose, so it can be edited and
    re-submitted by the frontend without any text-parsing on the way back."""
    locations: list[AudienceLocation] = []
    named_events: list = []
    list_name: str = ""
    apply_suppression: bool = True
    suppression_search_terms: list = []
    plan_summary: str = ""
    open_questions: list[OpenQuestion] = []


class AudiencePlanRequest(BaseModel):
    description: str
    qa: Optional[str] = ""


class AudiencePlanResponse(BaseModel):
    plan: AudiencePlan


class AudienceBuildRequest(BaseModel):
    plan: AudiencePlan


class AudienceListResult(BaseModel):
    list_id: str
    name: str
    url: str
    size: Optional[int] = None


class AudienceBuildResponse(BaseModel):
    master_list: AudienceListResult
    suppression_list: Optional[AudienceListResult] = None


# --- Implementation ---

class ImplementationSingleRequest(BaseModel):
    email_id: str
    list_id: str
    send_date: str  # YYYY-MM-DD — display/reminder only, never used to schedule in HubSpot
    send_time: str  # HH:MM


class ImplementationSingleResponse(BaseModel):
    email_id: str
    list_id: str
    draft_url: str
    send_date: str
    send_time: str


class SequenceStageSchedule(BaseModel):
    date: str  # YYYY-MM-DD
    time: str  # HH:MM


class ImplementationSequenceRequest(BaseModel):
    list_id: str
    invite_email_id: str
    reminder_email_id: str
    deadline_email_id: str
    invite: SequenceStageSchedule
    reminder: SequenceStageSchedule
    deadline: SequenceStageSchedule
    workflow_name: str = ""


class ImplementationSequenceResponse(BaseModel):
    invite_email_id: str
    invite_draft_url: str
    workflow_id: str
    workflow_url: str
    workflow_enabled: bool
