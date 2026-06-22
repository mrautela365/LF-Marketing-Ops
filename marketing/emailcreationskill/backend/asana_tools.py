"""
Asana REST API helpers for the /api/plan-from-asana endpoint.
Reads tasks, subtasks, and comments; extracts fields for the Email Brief.
"""
import re
import requests
from config import ASANA_ACCESS_TOKEN


def _headers() -> dict:
    return {"Authorization": f"Bearer {ASANA_ACCESS_TOKEN}", "Accept": "application/json"}


def parse_task_gid(url: str) -> str:
    """Extract task GID from an Asana task URL.

    Handles:
      https://app.asana.com/0/PROJECT/TASK
      https://app.asana.com/0/PROJECT/TASK/f
      https://app.asana.com/1/WORKSPACE/project/PROJECT/task/TASK
      https://app.asana.com/1/WORKSPACE/project/PROJECT/task/TASK?focus=true
    """
    # Strip query string and fragment
    url = url.strip().split("?")[0].split("#")[0].rstrip("/")

    # New format: .../task/{gid}
    m = re.search(r"/task/(\d+)", url)
    if m:
        return m.group(1)

    # Old format: .../0/PROJECT/TASK or .../0/PROJECT/TASK/f
    if url.endswith("/f"):
        url = url[:-2]
    gid = url.split("/")[-1]
    if gid.isdigit():
        return gid

    raise ValueError(
        f"Could not extract a numeric task ID from URL: {url}\n"
        "Expected format: https://app.asana.com/0/<project>/<task_id> "
        "or https://app.asana.com/1/<workspace>/project/<project>/task/<task_id>"
    )


def get_task(gid: str) -> dict:
    resp = requests.get(
        f"https://app.asana.com/api/1.0/tasks/{gid}",
        headers=_headers(),
        params={"opt_fields": "name,notes,due_on,projects.name,custom_fields,permalink_url"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("data", {})


def get_subtasks(gid: str) -> list:
    resp = requests.get(
        f"https://app.asana.com/api/1.0/tasks/{gid}/subtasks",
        headers=_headers(),
        params={"opt_fields": "name,notes,completed,gid"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("data", [])


def get_stories(gid: str) -> list:
    """Return only comment-type stories (not system events)."""
    resp = requests.get(
        f"https://app.asana.com/api/1.0/tasks/{gid}/stories",
        headers=_headers(),
        params={"opt_fields": "text,type,created_at,created_by.name"},
        timeout=15,
    )
    resp.raise_for_status()
    return [s for s in resp.json().get("data", []) if s.get("type") == "comment"]


# ── URL extraction helpers ────────────────────────────────────────────────────

def _urls_in(text: str) -> list:
    return re.findall(r"https?://[^\s\)\]>\"',]+", text or "")


def _find_google_doc(texts: list) -> str:
    for text in texts:
        for url in _urls_in(text):
            if "docs.google.com/document" in url:
                return url.rstrip(".,;)")
    return ""


_LF_DOMAINS = (
    "linuxfoundation.org", "lfresearch.org", "cncf.io",
    "events.linux", "openssf.org", "pytorch.org", "opensearch.org",
)

def _find_event_url(texts: list) -> str:
    for text in texts:
        for url in _urls_in(text):
            if any(d in url for d in _LF_DOMAINS):
                if not any(skip in url for skip in ("asana.com", "hubspot.com", "docs.google.com")):
                    return url.rstrip(".,;)")
    return ""


# ── Brief extraction ──────────────────────────────────────────────────────────

def extract_brief(task: dict, subtasks: list, all_stories: dict) -> dict:
    """
    Parse task + subtasks + their stories into an Email Brief dict.
    all_stories maps task GID → list of story dicts.
    """
    task_gid   = task.get("gid", "")
    task_name  = task.get("name", "")
    task_notes = task.get("notes", "") or ""

    # Collect all text in one flat list for URL scanning
    all_text: list[str] = [task_notes]
    for story in all_stories.get(task_gid, []):
        all_text.append(story.get("text", "") or "")
    for st in subtasks:
        all_text.append(st.get("notes", "") or "")
        for story in all_stories.get(st.get("gid", ""), []):
            all_text.append(story.get("text", "") or "")

    # Google Doc — prioritise "Content" subtask stories
    content_doc_url = ""
    for st in subtasks:
        if "content" in st.get("name", "").lower():
            doc_texts = [st.get("notes", "") or ""]
            for s in all_stories.get(st.get("gid", ""), []):
                doc_texts.append(s.get("text", "") or "")
            content_doc_url = _find_google_doc(doc_texts)
            if content_doc_url:
                break
    if not content_doc_url:
        content_doc_url = _find_google_doc(all_text)

    # Audience instructions — from "List Pull" or "Audience" subtask
    audience_instructions = ""
    for st in subtasks:
        if any(kw in st.get("name", "").lower() for kw in ("list pull", "list", "audience")):
            parts = [st.get("notes", "") or ""]
            for s in all_stories.get(st.get("gid", ""), []):
                parts.append(s.get("text", "") or "")
            audience_instructions = "\n".join(p for p in parts if p.strip())[:600]
            break

    # Event URL
    event_url = _find_event_url(all_text)

    # Brand from task name: "26Q2 - LF Research - Campaign Name"
    brand_name = ""
    m = re.match(r"^\d{2}Q\d\s*[-–]\s*(.+?)\s*[-–]", task_name)
    if m:
        brand_name = m.group(1).strip()

    # Due date + project
    due_on       = task.get("due_on", "")
    projects     = task.get("projects") or []
    project_name = projects[0].get("name", "") if projects else ""

    return {
        "task_name":             task_name,
        "email_name":            task_name,
        "brand_name":            brand_name,
        "project_name":          project_name,
        "content_doc_url":       content_doc_url,
        "audience_instructions": audience_instructions,
        "event_url":             event_url,
        "due_on":                due_on,
        "subtask_names":         [st.get("name", "") for st in subtasks],
    }
