"""
Pure UTM URL-tagging helpers — no HubSpot API dependency.
Used by hubspot_tools.update_email_content() to tag every outbound link.
"""
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from bs4 import BeautifulSoup

UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")


def add_utm(url: str, utm_params: dict, utm_content: str = "") -> str:
    """
    Merge utm_source/utm_medium/utm_campaign/utm_content into url's query string.
    No-op if url is empty/falsy, utm_params is empty, or the url already carries a
    non-empty utm_campaign (never double-tag pre-tagged links).
    """
    if not url or not utm_params:
        return url
    if url.startswith(("mailto:", "tel:", "#")):
        return url

    scheme, netloc, path, query, fragment = urlsplit(url)
    existing = parse_qsl(query, keep_blank_values=True)
    if any(k == "utm_campaign" and v for k, v in existing):
        return url

    params = dict(existing)
    params["utm_source"]   = utm_params.get("utm_source", "email")
    params["utm_medium"]   = utm_params.get("utm_medium", "email")
    params["utm_campaign"] = utm_params.get("utm_campaign", "")
    if utm_content:
        params["utm_content"] = utm_content
    if utm_params.get("utm_term"):
        params["utm_term"] = utm_params["utm_term"]

    new_query = urlencode(params)
    return urlunsplit((scheme, netloc, path, new_query, fragment))


def slugify_utm_content(text: str, suffix: str = "cta") -> str:
    """'Register Now' -> 'register-now-cta'."""
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    if not slug:
        slug = suffix
    elif suffix and not slug.endswith(suffix):
        slug = f"{slug}-{suffix}"
    return slug


def tag_html_links(html: str, utm_params: dict, prefix: str = "body-link") -> str:
    """
    Tag every <a href> in a rich_text HTML fragment, skipping mailto:/tel:/anchor-only
    links and any link that already carries a non-empty utm_campaign.
    """
    if not html or not utm_params:
        return html

    soup = BeautifulSoup(html, "html.parser")
    count = 0
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith(("mailto:", "tel:", "#")):
            continue
        count += 1
        a["href"] = add_utm(href, utm_params, f"{prefix}-{count}")

    return str(soup)
