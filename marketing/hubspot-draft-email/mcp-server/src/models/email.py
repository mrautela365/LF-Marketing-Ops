"""Pydantic models for the HubSpot Draft Email MCP server."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator


# ── Request models ────────────────────────────────────────────────────────────

class UtmSpecRequest(BaseModel):
    source: str = "hubspot"
    medium: str = "email"
    campaign: str = Field(..., description="e.g. '26q2-oss-india-2026'")
    content: str = Field("", description="CTA descriptor, e.g. 'register-cta'")
    term: str = Field("", description="Audience segment (optional)")


class CreateDraftRequest(BaseModel):
    name: str = Field(..., description="Email name, e.g. '26Q2 - LF Events - OSS India 2026'")
    subject: str = Field(..., description="Subject line (≤60 chars recommended)")
    preheader: str = Field("", description="Preheader text (≤100 chars recommended)")
    from_name: str = Field(..., description="Sender display name, e.g. 'LF Events'")
    from_email: str = Field(..., description="Sender email address — must be brand domain")
    reply_to: str = Field(..., description="Reply-to address — must be a monitored inbox")
    body_html: str = Field(..., description="Full email HTML body")
    subscription_type_id: str = Field(
        ..., description="HubSpot subscription type ID — must be confirmed by user"
    )
    utm_spec: UtmSpecRequest | None = None
    audience_list_ids: list[str] = Field(default_factory=list)
    suppression_list_ids: list[str] = Field(default_factory=list)
    scheduled_at: str | None = Field(
        None, description="ISO 8601 UTC datetime for scheduled send, e.g. '2026-06-15T14:00:00Z'"
    )

    @field_validator("from_email")
    @classmethod
    def from_email_not_freemail(cls, v: str) -> str:
        freemail = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com"}
        domain = v.split("@")[-1].lower() if "@" in v else ""
        if domain in freemail:
            raise ValueError(
                f"Freemail domain '{domain}' is not allowed for marketing sends. "
                "Use a brand domain address."
            )
        return v

    @field_validator("subscription_type_id")
    @classmethod
    def subscription_type_required(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError(
                "subscription_type_id is required. "
                "Use list_hubspot_subscription_types to get valid IDs, "
                "present them to the user, and confirm the correct one."
            )
        return v


class UpdateDraftRequest(BaseModel):
    name: str | None = None
    subject: str | None = None
    previewText: str | None = Field(None, alias="preheader")
    fromName: str | None = Field(None, alias="from_name")
    fromEmail: str | None = Field(None, alias="from_email")
    replyTo: str | None = Field(None, alias="reply_to")
    subscriptionId: str | None = Field(None, alias="subscription_type_id")

    model_config = {"populate_by_name": True}

    def to_hubspot_patch(self) -> dict[str, Any]:
        """Return only the non-None fields in HubSpot API key names."""
        mapping = {
            "name": self.name,
            "subject": self.subject,
            "previewText": self.previewText,
            "fromName": self.fromName,
            "fromEmail": self.fromEmail,
            "replyTo": self.replyTo,
            "subscriptionId": self.subscriptionId,
        }
        return {k: v for k, v in mapping.items() if v is not None}


class QaRequest(BaseModel):
    draft: dict[str, Any] = Field(..., description="Draft spec dict (same shape as CreateDraftRequest)")
    audience_list_ids: list[str] = Field(default_factory=list)
    suppression_list_ids: list[str] = Field(default_factory=list)


class DeleteDraftRequest(BaseModel):
    draft_id: str
    confirmed_name: str = Field(..., description="Human-readable email name for confirmation display")


class ScheduleRequest(BaseModel):
    draft_id: str
    scheduled_at_iso: str = Field(
        ..., description="ISO 8601 UTC datetime, e.g. '2026-06-15T14:00:00Z'"
    )


class ApplyUtmRequest(BaseModel):
    draft_id: str
    utm_campaign: str = Field(..., description="Campaign slug, e.g. '26q2-oss-india-2026'")
    utm_content_map: dict[str, str] | None = Field(
        None, description="Optional map of original URL → utm_content descriptor"
    )


class SaveCredentialsRequest(BaseModel):
    hubspot_api_key: str | None = None
    asana_pat: str | None = None


# ── Response models ────────────────────────────────────────────────────────────

class ApiResponse(BaseModel):
    success: bool
    data: Any = None
    error: str | None = None
