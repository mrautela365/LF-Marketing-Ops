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
        month_re = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
                    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")
        # Month-first: "June 15, 2026" / "June 15-16, 2026"
        date_patterns = re.findall(
            month_re + r"[\s,]+\d{1,2}(?:st|nd|rd|th)?"
            r"(?:[\s,–\-]+\d{1,2}(?:st|nd|rd|th)?[\s,]+)?20\d{2}\b",
            body_text,
        )
        # Day-first: "15-16 June 2026" / "15 June 2026"
        day_first = re.findall(
            r"\b\d{1,2}(?:st|nd|rd|th)?(?:[-–]\d{1,2}(?:st|nd|rd|th)?)?\s+" + month_re + r"\s+20\d{2}\b",
            body_text,
        )
        # Normalize day-first → "June 15, 2026" so stage_detector can parse it
        def _normalize_day_first(s: str) -> str:
            m = re.match(
                r"(\d{1,2})(?:st|nd|rd|th)?(?:[-–]\d{1,2}(?:st|nd|rd|th)?)?\s+"
                r"(" + month_re[4:-1] + r")\s+(20\d{2})",
                s, re.I,
            )
            return f"{m.group(2)} {m.group(1)}, {m.group(3)}" if m else s

        normalized_day_first = [_normalize_day_first(d) for d in day_first]
        all_dates = list(dict.fromkeys(date_patterns + normalized_day_first))[:3]

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


def scrape_event_full(url: str) -> dict:
    """
    Enhanced event scraping: extends fetch_url with hero/logo images,
    speaker names, topic tags, and registration page details.
    """
    base = fetch_url(url)

    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, timeout=15, headers=headers, allow_redirects=True)
        resp.raise_for_status()

        from bs4 import BeautifulSoup
        from urllib.parse import urlparse, urljoin
        soup = BeautifulSoup(resp.text, "html.parser")
        parsed_url = urlparse(url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"

        # ── Hero image (OG image is most reliable) ───────────────────────────
        og_image = soup.find("meta", property="og:image")
        hero_image_url = og_image["content"].strip() if og_image and og_image.get("content") else ""

        # ── Logo ─────────────────────────────────────────────────────────────
        logo_url = ""
        for img in soup.find_all("img"):
            src = (img.get("src") or "").strip()
            alt = (img.get("alt") or "").lower()
            cls = " ".join(img.get("class") or []).lower()
            if any(kw in (src.lower() + alt + cls) for kw in ("logo", "brand")):
                if src.startswith("http"):
                    logo_url = src
                elif src.startswith("/"):
                    logo_url = base_url + src
                if logo_url:
                    break

        # ── Speakers ─────────────────────────────────────────────────────────
        speakers = []
        for el in soup.find_all(
            ["div", "article", "li", "section"],
            class_=re.compile(r"speaker|keynote|presenter", re.I),
        )[:8]:
            name_el = el.find(["h2", "h3", "h4", "strong"])
            if name_el:
                name = name_el.get_text(strip=True)
                if name and 3 < len(name) < 60 and name not in speakers:
                    speakers.append(name)

        # ── Topics / tracks ───────────────────────────────────────────────────
        topics = []
        for el in soup.find_all(
            ["span", "div", "li", "a"],
            class_=re.compile(r"topic|track|tag|category|label", re.I),
        )[:10]:
            text = el.get_text(strip=True)
            if text and 3 < len(text) < 50 and text not in topics:
                topics.append(text)

        # ── Sponsors / partners ───────────────────────────────────────────────
        sponsors = []
        # Strategy 1: elements whose class names contain sponsor/partner keywords
        for el in soup.find_all(
            ["div", "section", "article", "li", "figure"],
            class_=re.compile(r"sponsor|partner|supporter|exhibitor", re.I),
        )[:12]:
            # Prefer alt text of logo images, else visible text
            img = el.find("img")
            name = ""
            if img:
                name = (img.get("alt") or "").strip()
            if not name:
                name = el.get_text(separator=" ", strip=True)
            # Filter noise: skip generic section headings and very short/long strings
            if name and 2 < len(name) < 70 and name.lower() not in (
                "sponsors", "partners", "our sponsors", "our partners",
                "supported by", "thank you sponsors",
            ) and name not in sponsors:
                sponsors.append(name)
        # Strategy 2: headings like "Sponsors" / "Partners" followed by img elements
        for h in soup.find_all(["h2", "h3", "h4"], string=re.compile(r"sponsor|partner|exhibitor", re.I)):
            sibling = h.find_next_sibling()
            if sibling:
                for img in sibling.find_all("img")[:6]:
                    name = (img.get("alt") or "").strip()
                    if name and 2 < len(name) < 70 and name not in sponsors:
                        sponsors.append(name)

        # ── Registration URL ──────────────────────────────────────────────────
        reg_url = ""
        for a in soup.find_all("a", href=True):
            link_text = a.get_text(strip=True).lower()
            href = a["href"]
            if any(kw in link_text for kw in ("register", "get ticket", "buy ticket", "attend")):
                reg_url = urljoin(url, href)
                break

        # ── Scrape registration page ─────────────────────────────────────────
        reg_details: dict = {}
        if reg_url and reg_url.rstrip("/") != url.rstrip("/"):
            try:
                rr = requests.get(reg_url, timeout=10, headers=headers, allow_redirects=True)
                rr.raise_for_status()
                rt = BeautifulSoup(rr.text, "html.parser").get_text(separator=" ", strip=True)
                ticket_types = re.findall(
                    r"(?:Early[ -]Bird|Regular|Standard|Professional|Academic|Student)"
                    r"[^$\n]{0,40}\$[\d,]+",
                    rt,
                )
                deadlines = re.findall(
                    r"(?:deadline|closes?|ends?|last day)[^\n.]{0,60}"
                    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
                    r"[\s,]+\d{1,2}[^\n.]{0,20}",
                    rt, re.IGNORECASE,
                )
                reg_details = {
                    "url": reg_url,
                    "ticket_types": ticket_types[:3],
                    "deadlines": deadlines[:2],
                }
            except Exception:
                reg_details = {"url": reg_url}

        return {
            **base,
            "hero_image_url": hero_image_url,
            "logo_url": logo_url,
            "speakers": speakers[:8],
            "topics": topics[:6],
            "sponsors": sponsors[:8],
            "registration": reg_details,
        }

    except Exception:
        return {
            **base,
            "hero_image_url": "",
            "logo_url": "",
            "speakers": [],
            "topics": [],
            "sponsors": [],
            "registration": {},
        }


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
    inline_objects = doc.get("inlineObjects", {})
    parts = []
    for elem in doc.get("body", {}).get("content", []):
        para = elem.get("paragraph")
        if not para:
            continue
        style = para.get("paragraphStyle", {}).get("namedStyleType", "NORMAL_TEXT")
        runs = []
        for pe in para.get("elements", []):

            # ── Text run ──────────────────────────────────────────────────────
            tr = pe.get("textRun")
            if tr:
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
                continue

            # ── Inline image ──────────────────────────────────────────────────
            inline = pe.get("inlineObjectElement")
            if inline:
                obj_id   = inline.get("inlineObjectId", "")
                obj      = inline_objects.get(obj_id, {})
                embedded = obj.get("inlineObjectProperties", {}).get("embeddedObject", {})
                img_props = embedded.get("imageProperties", {})
                # sourceUri = original public URL; contentUri = Google-hosted (needs auth)
                src = img_props.get("sourceUri") or img_props.get("contentUri") or ""
                alt = embedded.get("title") or embedded.get("description") or ""
                if src:
                    runs.append(
                        f'<img src="{src}" alt="{alt}" '
                        f'style="max-width:100%;height:auto;display:block;" />'
                    )

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
