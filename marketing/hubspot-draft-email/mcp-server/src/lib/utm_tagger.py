"""
UTM URL tagging utilities.

Builds, validates, and repairs UTM-tagged URLs for HubSpot marketing emails.

Standard LF Marketing UTM schema:
  utm_source   = hubspot
  utm_medium   = email
  utm_campaign = {quarter}-{topic}-{year}   e.g. 26q2-oss-india-2026
  utm_content  = CTA descriptor             e.g. register-cta, header-link
  utm_term     = audience segment (optional)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import ParseResult, parse_qs, urlencode, urlparse, urlunparse

# Freemail domains that are never valid From addresses
FREEMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "icloud.com", "protonmail.com", "aol.com", "live.com",
}

# Role-based address prefixes that should never appear in send lists
ROLE_BASED_PREFIXES = {
    "info", "admin", "noreply", "no-reply", "support", "help",
    "contact", "sales", "marketing", "webmaster", "postmaster",
    "abuse", "security", "hr", "legal",
}

# Spam trigger words (case-insensitive)
SPAM_TRIGGER_WORDS = [
    "free", "guaranteed", "act now", "click here", "winner",
    "cash", "earn money", "make money", "you have been selected",
    "congratulations", "no cost", "risk free", "special promotion",
    "limited time", "order now", "buy now",
]

REQUIRED_UTM_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_content"}
OPTIONAL_UTM_PARAMS = {"utm_term"}


@dataclass
class UtmSpec:
    source: str = "hubspot"
    medium: str = "email"
    campaign: str = ""       # e.g. 26q2-oss-india-2026
    content: str = ""        # e.g. register-cta
    term: str = ""           # optional: audience segment


@dataclass
class LinkAuditResult:
    url: str
    has_utm: bool
    missing_params: list[str] = field(default_factory=list)
    corrected_url: str = ""
    issue: str = ""


def build_utm_url(base_url: str, spec: UtmSpec) -> str:
    """
    Append UTM parameters to base_url.
    Existing UTM params in the URL are replaced with the spec values.
    """
    parsed: ParseResult = urlparse(base_url)
    existing_qs = parse_qs(parsed.query, keep_blank_values=True)

    # Remove any existing UTM params so we don't duplicate
    utm_keys = REQUIRED_UTM_PARAMS | OPTIONAL_UTM_PARAMS
    cleaned_qs = {k: v for k, v in existing_qs.items() if k not in utm_keys}

    utm_params: dict[str, str] = {
        "utm_source": spec.source,
        "utm_medium": spec.medium,
        "utm_campaign": spec.campaign,
        "utm_content": spec.content,
    }
    if spec.term:
        utm_params["utm_term"] = spec.term

    # Merge: cleaned existing params + UTM params
    merged = {k: v[0] if isinstance(v, list) else v for k, v in cleaned_qs.items()}
    merged.update(utm_params)

    new_query = urlencode(merged)
    result = parsed._replace(query=new_query)
    return urlunparse(result)


def extract_links_from_html(html: str) -> list[str]:
    """
    Extract all href= URLs from HTML content.
    Returns unique URLs, excluding mailto:, tel:, and anchor-only (#) links.
    """
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', html, re.IGNORECASE)
    seen: set[str] = set()
    results: list[str] = []
    for href in hrefs:
        href = href.strip()
        if href.startswith(("#", "mailto:", "tel:", "{{")):
            continue
        if href not in seen:
            seen.add(href)
            results.append(href)
    return results


def audit_link(url: str, spec: UtmSpec | None = None) -> LinkAuditResult:
    """
    Audit a single URL for UTM compliance.
    Returns a LinkAuditResult with missing params and a corrected URL if needed.
    """
    # Placeholder / broken links
    if url in ("#", "", "http://example.com", "https://example.com"):
        return LinkAuditResult(
            url=url,
            has_utm=False,
            issue="Placeholder or example URL — must be replaced before sending.",
        )

    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    present = set(qs.keys())
    missing = sorted(REQUIRED_UTM_PARAMS - present)

    if not missing:
        return LinkAuditResult(url=url, has_utm=True)

    corrected = build_utm_url(url, spec) if spec else ""
    return LinkAuditResult(
        url=url,
        has_utm=False,
        missing_params=missing,
        corrected_url=corrected,
        issue=f"Missing UTM parameters: {', '.join(missing)}",
    )


def audit_all_links(html: str, spec: UtmSpec | None = None) -> list[dict[str, Any]]:
    """
    Extract all links from HTML and audit each for UTM compliance.
    Returns a list of audit result dicts for use in the QA runner.
    """
    links = extract_links_from_html(html)
    results = []
    for url in links:
        r = audit_link(url, spec)
        results.append(
            {
                "url": r.url,
                "has_utm": r.has_utm,
                "missing_params": r.missing_params,
                "corrected_url": r.corrected_url,
                "issue": r.issue,
            }
        )
    return results


def validate_from_email(email: str) -> tuple[bool, str]:
    """
    Validate a From address.
    Returns (is_valid, reason).
    Rejects: freemail domains, role-based addresses, missing domain.
    """
    email = email.strip().lower()
    if "@" not in email:
        return False, "Not a valid email address (missing @)."

    local, domain = email.rsplit("@", 1)

    if domain in FREEMAIL_DOMAINS:
        return False, f"Freemail domain '{domain}' is not allowed for marketing sends."

    if local in ROLE_BASED_PREFIXES:
        return False, (
            f"Role-based address '{local}@...' should not be used as a From address. "
            "Use a personal or branded sender."
        )

    return True, ""


def check_spam_triggers(text: str) -> list[str]:
    """
    Scan subject line or body for spam trigger words.
    Returns a list of found trigger words.
    """
    text_lower = text.lower()
    found = []
    for trigger in SPAM_TRIGGER_WORDS:
        if trigger in text_lower:
            found.append(trigger)
    return found


def validate_subject_line(subject: str) -> list[dict[str, str]]:
    """
    Validate a subject line against best-practice rules.
    Returns a list of issue dicts: {field, issue, severity}
    """
    issues = []

    if len(subject) > 60:
        issues.append(
            {
                "field": "subject_line",
                "issue": f"Subject is {len(subject)} chars — keep to ≤60 for optimal open rates.",
                "severity": "medium",
            }
        )
    if len(subject) < 10:
        issues.append(
            {
                "field": "subject_line",
                "issue": "Subject line is very short — may lack context for recipients.",
                "severity": "low",
            }
        )
    if subject == subject.upper() and len(subject) > 3:
        issues.append(
            {
                "field": "subject_line",
                "issue": "Subject is ALL CAPS — appears spammy and reduces open rates.",
                "severity": "high",
            }
        )
    triggers = check_spam_triggers(subject)
    if triggers:
        issues.append(
            {
                "field": "subject_line",
                "issue": f"Spam trigger words found: {', '.join(triggers)}",
                "severity": "high",
            }
        )
    if "!!!" in subject or subject.count("!") > 2:
        issues.append(
            {
                "field": "subject_line",
                "issue": "Excessive exclamation marks — looks spammy.",
                "severity": "medium",
            }
        )
    return issues


def validate_preheader(subject: str, preheader: str) -> list[dict[str, str]]:
    """
    Validate the preheader text.
    Returns a list of issue dicts.
    """
    issues = []

    if not preheader:
        issues.append(
            {
                "field": "preheader",
                "issue": "Preheader is empty — HubSpot will pull the first line of email body instead.",
                "severity": "medium",
            }
        )
        return issues

    if len(preheader) > 100:
        issues.append(
            {
                "field": "preheader",
                "issue": f"Preheader is {len(preheader)} chars — keep to ≤100 to avoid truncation.",
                "severity": "low",
            }
        )

    # Check if preheader just repeats the subject
    if subject and preheader.strip().lower() == subject.strip().lower():
        issues.append(
            {
                "field": "preheader",
                "issue": "Preheader repeats the subject line — it should add new information.",
                "severity": "medium",
            }
        )

    return issues
