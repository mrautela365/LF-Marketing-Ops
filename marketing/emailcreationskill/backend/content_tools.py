"""
Content preparation — Google Doc → HTML, raw HTML validation, plain text wrapping.
Also: URL scraping for event detail extraction.
"""
import re
import requests
from config import GOOGLE_SERVICE_ACCOUNT_FILE


def fetch_url(url: str) -> dict:
    """
    Fetch an event/campaign URL and extract structured details for email staging.
    Returns: brand_name, event_name, location, event_dates, description, organization, headings.
    """
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, timeout=15, headers=headers, allow_redirects=True)
        resp.raise_for_status()

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        # ── Event name ──────────────────────────────────────────────────────
        og_title   = soup.find("meta", property="og:title")
        title_tag  = soup.find("title")
        event_name = ""
        if og_title and og_title.get("content"):
            event_name = og_title["content"].strip()
        if not event_name and title_tag:
            event_name = title_tag.text.strip().split("|")[0].split("-")[0].strip()
        h1 = soup.find("h1")
        if not event_name and h1:
            event_name = h1.get_text(strip=True)

        # ── Organization / brand name ────────────────────────────────────────
        og_site      = soup.find("meta", property="og:site_name")
        organization = (og_site["content"].strip() if og_site and og_site.get("content") else "")
        # Fallback: try to extract from URL domain or title
        if not organization:
            domain = re.sub(r"https?://(www\.)?", "", url).split("/")[0]
            if "linuxfoundation" in domain:
                organization = "Linux Foundation"
            elif "cncf" in domain:
                organization = "CNCF"

        # ── Description ──────────────────────────────────────────────────────
        description = ""
        for meta in soup.find_all("meta"):
            name = (meta.get("name") or meta.get("property") or "").lower()
            if name in ("description", "og:description", "twitter:description"):
                description = (meta.get("content") or "").strip()
                if description:
                    break

        body_text = soup.get_text(separator=" ", strip=True)

        # ── Event dates ──────────────────────────────────────────────────────
        date_patterns = re.findall(
            r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
            r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
            r"[\s,]+\d{1,2}(?:st|nd|rd|th)?(?:[\s,–\-]+\d{1,2}(?:st|nd|rd|th)?[\s,]+)?20\d{2}\b",
            body_text,
        )
        # Also look for short date ranges like "June 23-25, 2026"
        short_dates = re.findall(
            r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
            r"[\s,]+\d{1,2}(?:[-–]\d{1,2})?,?\s*20\d{2}\b",
            body_text,
        )
        all_dates = list(dict.fromkeys(date_patterns + short_dates))[:3]

        # ── Location ─────────────────────────────────────────────────────────
        location = ""
        # Look for "in <City>" or "<City>, <Country>" near heading areas
        loc_patterns = [
            r"\bin\s+([A-Z][a-zA-Z\s]+,\s*[A-Z][a-zA-Z]+)\b",
            r"\b([A-Z][a-zA-Z]+,\s*(?:Japan|Germany|USA|UK|France|Spain|India|Canada|Australia))\b",
        ]
        for pat in loc_patterns:
            m = re.search(pat, body_text)
            if m:
                location = m.group(1).strip()
                break
        # Fallback: check URL slug for city hints
        if not location:
            slug = url.lower()
            city_hints = {
                "japan": "Japan", "europe": "Europe", "north-america": "North America",
                "india": "India", "china": "China", "tokyo": "Tokyo",
                "amsterdam": "Amsterdam", "paris": "Paris", "london": "London",
            }
            for k, v in city_hints.items():
                if k in slug:
                    location = v
                    break

        # ── H1–H3 headings ───────────────────────────────────────────────────
        headings = []
        for tag in ["h1", "h2", "h3"]:
            for el in soup.find_all(tag)[:5]:
                text = el.get_text(strip=True)
                if text and text not in headings:
                    headings.append(text)

        return {
            "url": url,
            "event_name": event_name,
            "brand_name": organization,
            "location": location,
            "event_dates": all_dates,
            "description": description,
            "headings": headings[:6],
            "body_preview": body_text[:2000],
        }
    except Exception as exc:
        return {"url": url, "error": str(exc)}


def prepare_content(content_input: str) -> str:
    """
    Accepts a Google Doc URL, raw HTML, or plain text.
    Returns clean email-ready HTML.
    """
    text = content_input.strip()
    if _is_google_doc_url(text):
        return _fetch_google_doc(text)
    if _looks_like_html(text):
        return text
    return _plain_to_html(text)


def _is_google_doc_url(text: str) -> bool:
    return bool(re.match(r"https://docs\.google\.com/document/", text))


def _looks_like_html(text: str) -> bool:
    return bool(re.search(r"<[a-zA-Z][^>]*>", text))


def _extract_doc_id(url: str) -> str:
    match = re.search(r"/document/d/([a-zA-Z0-9_-]+)", url)
    if not match:
        raise ValueError(f"Could not extract document ID from URL: {url}")
    return match.group(1)


def _fetch_google_doc(url: str) -> str:
    if not GOOGLE_SERVICE_ACCOUNT_FILE:
        raise ValueError(
            "Google Service Account file is not configured (GOOGLE_SERVICE_ACCOUNT_FILE). "
            "Please paste the email content directly instead of providing a Google Doc URL."
        )
    from googleapiclient.discovery import build
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_file(
        GOOGLE_SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/documents.readonly"],
    )
    service = build("docs", "v1", credentials=creds)
    doc = service.documents().get(documentId=_extract_doc_id(url)).execute()
    return _doc_to_html(doc)


def _doc_to_html(doc: dict) -> str:
    parts = []
    for elem in doc.get("body", {}).get("content", []):
        para = elem.get("paragraph")
        if not para:
            continue
        style = para.get("paragraphStyle", {}).get("namedStyleType", "NORMAL_TEXT")
        runs = []
        for pe in para.get("elements", []):
            tr = pe.get("textRun")
            if not tr:
                continue
            text = tr.get("content", "").rstrip("\n")
            if not text:
                continue
            ts = tr.get("textStyle") or {}
            if ts.get("bold"):
                text = f"<strong>{text}</strong>"
            if ts.get("italic"):
                text = f"<em>{text}</em>"
            link_url = (ts.get("link") or {}).get("url")
            if link_url:
                text = f'<a href="{link_url}">{text}</a>'
            runs.append(text)
        line = "".join(runs).strip()
        if not line:
            continue
        if style.startswith("HEADING_"):
            level = style[-1]
            parts.append(f"<h{level}>{line}</h{level}>")
        else:
            parts.append(f"<p>{line}</p>")
    return "\n".join(parts)


def _plain_to_html(text: str) -> str:
    return "\n".join(
        f"<p>{line}</p>" for line in text.split("\n") if line.strip()
    )
