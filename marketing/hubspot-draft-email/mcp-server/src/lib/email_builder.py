"""
Email payload builder.

Maps the simplified draft spec (from the web UI or MCP tools) to the
HubSpot Marketing v3 Emails API payload shape, and validates the spec
before any API call is made.
"""

from __future__ import annotations

import re
from typing import Any

from .utm_tagger import (
    UtmSpec,
    audit_all_links,
    validate_from_email,
    validate_preheader,
    validate_subject_line,
)

# Personalization token pattern: {{ contact.xxx }} or {{ contact.xxx | default: "yyy" }}
_TOKEN_RE = re.compile(r"\{\{\s*contact\.\w+\s*(?:\|[^}]*)?\}\}")
_TOKEN_WITHOUT_FALLBACK_RE = re.compile(
    r"\{\{\s*contact\.\w+\s*\}\}"  # no pipe = no default
)


def _has_unsubscribe_link(html: str) -> bool:
    """Check if the HTML contains an unsubscribe link."""
    lower = html.lower()
    return any(
        pattern in lower
        for pattern in [
            "unsubscribe",
            "opt-out",
            "opt out",
            "subscription preferences",
            "manage preferences",
            "email preferences",
        ]
    )


def _has_physical_address(html: str) -> bool:
    """Heuristic check for a physical mailing address in the footer."""
    lower = html.lower()
    address_signals = [
        "suite",
        "floor",
        "ave",
        "avenue",
        "street",
        "st.",
        "blvd",
        "road",
        "rd.",
        "way",
        "drive",
        "dr.",
        "p.o. box",
        "po box",
        # ZIP-code-like pattern: 5 digits
    ]
    has_signal = any(sig in lower for sig in address_signals)
    has_zip = bool(re.search(r"\b\d{5}(?:-\d{4})?\b", html))
    return has_signal or has_zip


def _tokens_without_fallback(html: str) -> list[str]:
    """Return personalization tokens that have no fallback value."""
    return _TOKEN_WITHOUT_FALLBACK_RE.findall(html)


def validate_draft_spec(spec: dict[str, Any]) -> list[dict[str, str]]:
    """
    Validate a draft spec dict before building the payload.

    Returns a list of issue dicts:
      { "field": str, "issue": str, "severity": "critical"|"high"|"medium"|"low" }

    severity=critical  → must be fixed before any draft is created
    severity=high      → blocks send approval; must be resolved
    severity=medium    → should be fixed; warn the user
    severity=low       → advisory; user may accept the risk
    """
    issues: list[dict[str, str]] = []

    name: str = spec.get("name", "").strip()
    subject: str = spec.get("subject", "").strip()
    preheader: str = spec.get("preheader", "").strip()
    from_email: str = spec.get("from_email", "").strip()
    reply_to: str = spec.get("reply_to", "").strip()
    body_html: str = spec.get("body_html", "").strip()
    subscription_type_id: str = spec.get("subscription_type_id", "").strip()

    # ── CRITICAL: required fields ────────────────────────────────────────────
    if not name:
        issues.append(
            {"field": "name", "issue": "Email name is required.", "severity": "critical"}
        )
    if not subject:
        issues.append(
            {"field": "subject", "issue": "Subject line is required.", "severity": "critical"}
        )
    if not from_email:
        issues.append(
            {"field": "from_email", "issue": "From email address is required.", "severity": "critical"}
        )
    if not subscription_type_id:
        issues.append(
            {
                "field": "subscription_type_id",
                "issue": (
                    "Subscription type is required. Use list_hubspot_subscription_types to "
                    "show the user the options and confirm the correct one."
                ),
                "severity": "critical",
            }
        )
    if not body_html:
        issues.append(
            {"field": "body_html", "issue": "Email body is required.", "severity": "critical"}
        )

    # Stop here if critical fields are missing — nothing else is useful
    if any(i["severity"] == "critical" for i in issues):
        return issues

    # ── HIGH: sender validation ──────────────────────────────────────────────
    from_valid, from_reason = validate_from_email(from_email)
    if not from_valid:
        issues.append({"field": "from_email", "issue": from_reason, "severity": "high"})

    if reply_to:
        reply_valid, reply_reason = validate_from_email(reply_to)
        if not reply_valid:
            issues.append({"field": "reply_to", "issue": reply_reason, "severity": "high"})
        # Flag noreply specifically
        local = reply_to.split("@")[0].lower()
        if local in {"noreply", "no-reply", "donotreply"}:
            issues.append(
                {
                    "field": "reply_to",
                    "issue": (
                        f"Reply-to '{reply_to}' is a no-reply address. "
                        "Use a monitored inbox — noreply addresses harm deliverability and user trust."
                    ),
                    "severity": "high",
                }
            )

    # ── HIGH: subject line ───────────────────────────────────────────────────
    issues.extend(validate_subject_line(subject))

    # ── HIGH: personalization tokens without fallbacks ───────────────────────
    bad_tokens = _tokens_without_fallback(body_html)
    if bad_tokens:
        issues.append(
            {
                "field": "body_html",
                "issue": (
                    f"Personalization tokens without fallback values: {', '.join(bad_tokens)}. "
                    "Add | default: 'there' (or similar) to avoid blank values for unmatched contacts."
                ),
                "severity": "high",
            }
        )

    # ── HIGH: unsubscribe link ───────────────────────────────────────────────
    if not _has_unsubscribe_link(body_html):
        issues.append(
            {
                "field": "body_html",
                "issue": (
                    "No unsubscribe link detected. CAN-SPAM/GDPR require a working "
                    "unsubscribe mechanism in every marketing email."
                ),
                "severity": "high",
            }
        )

    # ── MEDIUM: preheader ────────────────────────────────────────────────────
    issues.extend(validate_preheader(subject, preheader))

    # ── MEDIUM: physical address ─────────────────────────────────────────────
    if not _has_physical_address(body_html):
        issues.append(
            {
                "field": "body_html",
                "issue": (
                    "No physical mailing address detected in the email body. "
                    "Required by CAN-SPAM and considered best practice globally."
                ),
                "severity": "medium",
            }
        )

    # ── MEDIUM: UTM links ────────────────────────────────────────────────────
    utm_spec_raw = spec.get("utm_spec")
    utm_spec = UtmSpec(**utm_spec_raw) if utm_spec_raw else None
    link_audits = audit_all_links(body_html, utm_spec)
    broken = [a for a in link_audits if a["issue"] and "Placeholder" in a["issue"]]
    missing_utm = [a for a in link_audits if not a["has_utm"] and not a["issue"].startswith("Placeholder")]

    for a in broken:
        issues.append(
            {
                "field": "body_html",
                "issue": f"Broken/placeholder link: {a['url']}",
                "severity": "high",
            }
        )
    if missing_utm:
        urls = ", ".join(a["url"][:60] for a in missing_utm[:3])
        issues.append(
            {
                "field": "body_html",
                "issue": (
                    f"{len(missing_utm)} link(s) missing UTM parameters: {urls}"
                    + ("..." if len(missing_utm) > 3 else "")
                ),
                "severity": "medium",
            }
        )

    return issues


def build_email_payload(spec: dict[str, Any]) -> dict[str, Any]:
    """
    Convert a validated draft spec to the HubSpot Marketing v3 Emails API payload.

    Caller must run validate_draft_spec() first and abort on critical/high issues.
    """
    payload: dict[str, Any] = {
        "name": spec["name"],
        "subject": spec["subject"],
        "fromName": spec.get("from_name", ""),
        "fromEmail": spec["from_email"],
        "replyTo": spec.get("reply_to", spec["from_email"]),
        "previewText": spec.get("preheader", ""),
        "content": {
            "body": spec.get("body_html", ""),
        },
        "sendOnPublish": False,  # Always create as draft — never auto-send
    }

    # Subscription type
    if spec.get("subscription_type_id"):
        payload["subscriptionId"] = spec["subscription_type_id"]

    # Schedule (optional — only set if user confirmed send time)
    if spec.get("scheduled_at"):
        payload["scheduledAt"] = spec["scheduled_at"]

    return payload
