import re
import httpx
from bs4 import BeautifulSoup
from typing import Optional


def fetch_google_doc_html(doc_url: str) -> dict:
    """Fetch a Google Doc and return clean email-ready HTML."""
    # Extract doc ID
    match = re.search(r"/d/([a-zA-Z0-9_-]+)", doc_url)
    if not match:
        return {"error": f"Could not extract Google Doc ID from URL: {doc_url}"}

    doc_id = match.group(1)
    export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=html"

    try:
        resp = httpx.get(export_url, follow_redirects=True, timeout=15)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403):
            return {"error": "Google Doc is not publicly accessible. Ask the requester to share with 'Anyone with the link can view'."}
        return {"error": f"Failed to fetch Google Doc: {e}"}

    soup = BeautifulSoup(resp.text, "html.parser")
    body = soup.find("body")
    if not body:
        return {"error": "Could not parse Google Doc HTML body."}

    # Remove Google Docs wrapper styles, keep semantic tags
    for tag in body.find_all(True):
        tag.attrs = {k: v for k, v in tag.attrs.items() if k in ("href", "src", "alt")}

    clean_html = body.decode_contents()
    return {"html": clean_html, "doc_id": doc_id}


def validate_links(html: str) -> dict:
    """Check all href links in HTML for basic validity. Returns broken/suspicious links."""
    soup = BeautifulSoup(html, "html.parser")
    links = [a.get("href", "") for a in soup.find_all("a") if a.get("href")]

    broken = []
    for link in links:
        if not link:
            broken.append({"url": link, "reason": "empty href"})
        elif link.startswith(("javascript:", "#")):
            broken.append({"url": link, "reason": "non-navigable link"})
        elif not link.startswith(("http://", "https://", "mailto:")):
            broken.append({"url": link, "reason": "relative or unknown scheme"})

    return {
        "total_links": len(links),
        "broken_links": broken,
        "all_links": links,
    }
