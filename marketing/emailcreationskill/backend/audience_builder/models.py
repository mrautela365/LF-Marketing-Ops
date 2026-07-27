"""
Pydantic models for the Audience Builder tab (existing-list discovery + master
list composition). Kept local to this feature package rather than added to the
app-wide backend/models.py, since they aren't used anywhere else.
"""
from pydantic import BaseModel


class DiscoverListsRequest(BaseModel):
    event_url: str
    qa: str = ""


class DiscoveredList(BaseModel):
    list_id: str
    name: str
    signal: str  # project_opt_in | lf_newsletter_opt_in | event_registration | education_enrollment | page_view | uncertain
    size: int | None = None
    reason: str = ""
    list_type: str = ""  # HubSpot processingType, e.g. DYNAMIC | MANUAL | SNAPSHOT — real field, not computed


class ComposeMasterListRequest(BaseModel):
    list_ids: list[str]
    name: str = ""
    event_url: str = ""
    brand_short: str = ""
    event_name: str = ""
    exclude_list_ids: list[str] = []


class ComposeMasterListResponse(BaseModel):
    list_id: str
    name: str
    hubspot_url: str
    size: int | str = "unknown"
    source_list_ids: list[str]
    suppression_list_id: str = ""
    suppression_name: str = ""
    suppression_hubspot_url: str = ""
    suppression_size: int | str = "unknown"


class SuppressionList(BaseModel):
    key: str
    label: str
    list_id: str
    name: str
    size: int | None = None
    category: str = "standard"  # standard | brand | event_specific


class PreviewCountRequest(BaseModel):
    list_ids: list[str]


class PreviewCountResponse(BaseModel):
    exact: bool
    estimate: int
    count: int
    reason: str = ""
