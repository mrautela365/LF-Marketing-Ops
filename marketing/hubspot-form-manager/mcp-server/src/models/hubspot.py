"""Pydantic models for HubSpot API request/response shapes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FormField(BaseModel):
    name: str = Field(..., description="Human-readable field label, e.g. 'First Name'")
    type: str = Field(
        "text",
        description="Field type: text | email | phone | textarea | select | checkbox | number | country | date",
    )
    required: bool = False
    options: list[str] = Field(default_factory=list, description="Options for select/dropdown fields")


class CreateFormRequest(BaseModel):
    name: str = Field(..., description="Form name, e.g. '26Q2 - LF Events - CloudNativeCon 2026'")
    brand: str = Field(..., description="Brand/business unit (e.g. LF Events, AAIF, OpenSSF). Required — never assumed.")
    fields: list[FormField] = Field(default_factory=list)
    submit_button_text: str = "Submit"
    thank_you_message: str = "Thank you for your submission."
    notification_emails: list[str] = Field(
        default_factory=list, description="Email addresses to notify on submission. Empty = no notifications."
    )
    subscription_type_id: str = Field(
        ..., description="HubSpot subscription type ID. Use list_hubspot_subscription_types to get valid IDs."
    )
    # Legal consent / privacy text (optional — defaults to standard LF privacy text)
    privacy_text: str | None = Field(
        default=None,
        description="HTML privacy/consent text shown on the form. Defaults to standard LF policy text."
    )
    # Autoresponder email (optional)
    autoresponder_subject: str | None = None
    autoresponder_from_name: str | None = None
    autoresponder_from_email: str | None = None
    autoresponder_body_html: str | None = None
    # Workflow enrollment (optional)
    workflow_name_query: str | None = None


class UpdateFormDetailsRequest(BaseModel):
    name: str | None = Field(default=None, description="New form name")
    submit_button_text: str | None = Field(default=None, description="New submit button label")
    thank_you_message: str | None = Field(default=None, description="New post-submit thank-you message")
    notification_emails: list[str] | None = Field(
        default=None, description="New notification list. Pass empty list to disable all."
    )


class DeleteFormsRequest(BaseModel):
    form_ids: list[str] = Field(..., description="List of HubSpot form GUIDs to delete")
    confirmed_names: list[str] = Field(..., description="Matching human-readable names for confirmation display")


class UpdateNotificationsRequest(BaseModel):
    form_id: str
    notification_emails: list[str] = Field(
        default_factory=list, description="New notification list. Empty = disable all."
    )


class CreateEmailRequest(BaseModel):
    name: str
    subject: str
    from_name: str
    from_email: str
    body_html: str
    is_transactional: bool = True


class PostCommentRequest(BaseModel):
    task_id: str = Field(..., description="Asana task GID or full Asana task URL")
    text: str = Field(..., description="Comment text to post")


class AsanaTaskUrlRequest(BaseModel):
    url: str = Field(..., description="Asana task URL or bare task GID")


class SaveCredentialsRequest(BaseModel):
    hubspot_api_key: str | None = None
    asana_pat: str | None = None


class ApiResponse(BaseModel):
    success: bool
    data: Any = None
    error: str | None = None
