"""Pydantic request/response models for the audience-builder routes.
Ported verbatim from emailcreationskill/backend/audience_builder/models.py —
no external deps beyond pydantic, no adaptation needed."""
from typing import List, Optional

from pydantic import BaseModel


class DiscoverListsRequest(BaseModel):
    event_url: str
    qa: str = ""


class DiscoveredList(BaseModel):
    list_id: str
    name: str
    signal: str
    size: Optional[int] = None
    reason: str = ""
    list_type: str = ""
    scope: str = ""


class ComposeMasterListRequest(BaseModel):
    list_ids: List[str]
    name: str = ""
    event_url: str = ""
    brand_short: str = ""
    event_name: str = ""
    exclude_list_ids: List[str] = []


class ComposeMasterListResponse(BaseModel):
    list_id: str
    name: str
    hubspot_url: str
    size: str = "unknown"
    source_list_ids: List[str] = []
    suppression_list_id: str = ""
    suppression_name: str = ""
    suppression_hubspot_url: str = ""
    suppression_size: str = "unknown"


class SuppressionList(BaseModel):
    key: str
    label: str
    list_id: str
    name: str
    size: Optional[int] = None
    category: str = "standard"


class PreviewCountRequest(BaseModel):
    list_ids: List[str]


class PreviewCountResponse(BaseModel):
    exact: bool
    estimate: bool
    count: int
    reason: str = ""
