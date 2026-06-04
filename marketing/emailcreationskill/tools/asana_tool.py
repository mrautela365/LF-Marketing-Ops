import re
import httpx
from email_service.config import settings

ASANA_BASE = "https://app.asana.com/api/1.0"


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.asana_token}"}


def get_asana_task(task_url: str) -> dict:
    """Fetch an Asana task by URL and extract email request fields."""
    match = re.search(r"/(\d+)(?:/f)?$", task_url)
    if not match:
        return {"error": f"Could not extract task ID from URL: {task_url}"}

    task_id = match.group(1)
    params = {"opt_fields": "name,notes,custom_fields,followers,projects"}
    resp = httpx.get(f"{ASANA_BASE}/tasks/{task_id}", headers=_headers(), params=params)
    resp.raise_for_status()
    task = resp.json().get("data", {})

    fields = {
        "task_id": task_id,
        "task_name": task.get("name", ""),
        "notes": task.get("notes", ""),
        "brand": None,
        "content_url": None,
        "subject": None,
        "preview_text": None,
        "send_date": None,
        "audience": None,
        "email_type": None,
        "reviewers": [],
    }

    # Map custom fields by name
    for cf in task.get("custom_fields", []):
        name = (cf.get("name") or "").lower()
        value = cf.get("text_value") or cf.get("display_value") or ""
        if "project" in name or "business unit" in name or "brand" in name:
            fields["brand"] = value
        elif "content" in name or "copy" in name:
            fields["content_url"] = value
        elif "subject" in name:
            fields["subject"] = value
        elif "preview" in name:
            fields["preview_text"] = value
        elif "send date" in name or "target" in name:
            fields["send_date"] = value
        elif "audience" in name or "list" in name:
            fields["audience"] = value
        elif "marketing or transactional" in name or "email type" in name:
            fields["email_type"] = value

    # Followers as reviewers
    fields["reviewers"] = [f.get("name", "") for f in task.get("followers", [])]

    return fields
