import httpx
from typing import Optional
from email_service.config import settings

BASE = "https://api.hubapi.com"
PORTAL_ID = settings.hubspot_portal_id


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.hubspot_access_token}", "Content-Type": "application/json"}


def search_brand_emails(brand_name: str) -> dict:
    """Search for emails matching a brand name, sorted by most recently sent."""
    params = {"limit": 20, "property": ["id", "name", "state", "subject", "fromName", "fromEmail",
                                         "updatedAt", "publishDate"]}
    resp = httpx.get(f"{BASE}/marketing/v3/emails", headers=_headers(), params=params)
    resp.raise_for_status()
    emails = resp.json().get("results", [])
    brand_lower = brand_name.lower()
    matches = [e for e in emails if brand_lower in e.get("name", "").lower()]
    sent = [e for e in matches if e.get("state") == "PUBLISHED"]
    sent.sort(key=lambda e: e.get("publishDate", ""), reverse=True)
    return {"emails": sent, "all_matches": matches}


def get_email_details(email_id: str) -> dict:
    """Get full metadata for a HubSpot email including suppression/send lists."""
    resp = httpx.get(f"{BASE}/marketing/v3/emails/{email_id}", headers=_headers())
    resp.raise_for_status()
    return resp.json()


def clone_email(email_id: str, clone_name: str) -> dict:
    """Clone a HubSpot email. Returns the new email object."""
    body = {"id": email_id, "cloneName": clone_name}
    resp = httpx.post(f"{BASE}/marketing/v3/emails/clone", headers=_headers(), json=body)
    resp.raise_for_status()
    return resp.json()


def update_email_settings(email_id: str, settings_dict: dict) -> dict:
    """PATCH email metadata: subject, preview, from name/address, subscription type, send/suppress lists."""
    resp = httpx.patch(f"{BASE}/marketing/v3/emails/{email_id}", headers=_headers(), json=settings_dict)
    resp.raise_for_status()
    return resp.json()


def update_email_content(email_id: str, html: str) -> dict:
    """Replace the email body content."""
    body = {"content": {"body": html}}
    resp = httpx.patch(f"{BASE}/marketing/v3/emails/{email_id}", headers=_headers(), json=body)
    resp.raise_for_status()
    return resp.json()


def get_hubspot_list(list_name_or_id: str) -> dict:
    """Look up a HubSpot contact list by name or ID."""
    # Try as numeric ID first
    if list_name_or_id.isdigit():
        resp = httpx.get(f"{BASE}/crm/v3/lists/{list_name_or_id}", headers=_headers())
        resp.raise_for_status()
        return resp.json()
    # Search by name
    params = {"count": 50, "query": list_name_or_id}
    resp = httpx.get(f"{BASE}/contacts/v1/lists", headers=_headers(), params=params)
    resp.raise_for_status()
    lists = resp.json().get("lists", [])
    matches = [l for l in lists if list_name_or_id.lower() in l.get("name", "").lower()]
    return {"lists": matches}


def create_static_list(name: str, csv_path: Optional[str] = None) -> dict:
    """Create a static contact list. Optionally import from CSV path."""
    body = {"name": name, "listType": "STATIC", "objectTypeId": "0-1"}
    resp = httpx.post(f"{BASE}/crm/v3/lists", headers=_headers(), json=body)
    resp.raise_for_status()
    result = resp.json()
    if csv_path:
        result["csv_import_note"] = f"CSV import for {csv_path} must be done via HubSpot import API with the returned list ID."
    return result
