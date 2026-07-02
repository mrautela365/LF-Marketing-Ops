"""
QA Runner — five-section pre-send checklist.

Mirrors the marketing-qa skill's five-section framework:
  4.1  Sender & Deliverability
  4.2  Subscription & Preference Center
  4.3  Consent Compliance
  4.4  Content QA
  4.5  Sense Check

Each section returns a list of QACheck objects.
The overall verdict is READY / NEEDS_CHANGES / BLOCKED based on severity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .utm_tagger import (
    audit_all_links,
    check_spam_triggers,
    validate_from_email,
    validate_preheader,
    validate_subject_line,
)

Severity = Literal["critical", "high", "medium", "low", "info"]
Status = Literal["pass", "fail", "warn", "info"]
Verdict = Literal["READY_TO_SEND", "NEEDS_CHANGES", "BLOCKED"]


@dataclass
class QACheck:
    section: str
    check: str
    status: Status
    issue: str = ""
    severity: Severity = "info"
    fix: str = ""
    deep_link: str = ""


@dataclass
class QAReport:
    checks: list[QACheck] = field(default_factory=list)
    verdict: Verdict = "READY_TO_SEND"
    summary: str = ""
    claude_can_fix: list[str] = field(default_factory=list)
    manual_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "summary": self.summary,
            "checks": [
                {
                    "section": c.section,
                    "check": c.check,
                    "status": c.status,
                    "issue": c.issue,
                    "severity": c.severity,
                    "fix": c.fix,
                    "deep_link": c.deep_link,
                }
                for c in self.checks
            ],
            "claude_can_fix": self.claude_can_fix,
            "manual_actions": self.manual_actions,
        }


def _verdict_from_checks(checks: list[QACheck]) -> Verdict:
    severities = {c.severity for c in checks if c.status in ("fail", "warn")}
    if "critical" in severities:
        return "BLOCKED"
    if "high" in severities:
        return "NEEDS_CHANGES"
    if "medium" in severities:
        return "NEEDS_CHANGES"
    return "READY_TO_SEND"


def run_qa(
    draft: dict[str, Any],
    portal_id: str = "",
    audience_lists: list[dict[str, Any]] | None = None,
    suppression_lists: list[dict[str, Any]] | None = None,
) -> QAReport:
    """
    Run the full 5-section QA suite against a draft email spec.

    draft keys:
      name, subject, preheader, from_name, from_email, reply_to,
      body_html, subscription_type_id, utm_spec (dict|None),
      audience_list_ids (list[str]), suppression_list_ids (list[str])

    Returns a QAReport with all checks and an overall verdict.
    """
    checks: list[QACheck] = []
    claude_can_fix: list[str] = []
    manual_actions: list[str] = []

    subject: str = draft.get("subject", "")
    preheader: str = draft.get("preheader", "")
    from_email: str = draft.get("from_email", "")
    reply_to: str = draft.get("reply_to", "")
    body_html: str = draft.get("body_html", "")
    subscription_type_id: str = draft.get("subscription_type_id", "")
    audience_list_ids: list[str] = draft.get("audience_list_ids", [])
    suppression_list_ids: list[str] = draft.get("suppression_list_ids", [])

    # ── 4.1 Sender & Deliverability ──────────────────────────────────────────

    from_valid, from_reason = validate_from_email(from_email)
    checks.append(
        QACheck(
            section="4.1 Sender & Deliverability",
            check="From email is brand domain (no freemail)",
            status="pass" if from_valid else "fail",
            issue=from_reason,
            severity="high" if not from_valid else "info",
            fix=(
                "Replace with a branded sender address (e.g. events@linuxfoundation.org)"
                if not from_valid
                else ""
            ),
        )
    )

    # Reply-to check
    if reply_to:
        reply_local = reply_to.split("@")[0].lower() if "@" in reply_to else ""
        is_noreply = reply_local in {"noreply", "no-reply", "donotreply"}
        checks.append(
            QACheck(
                section="4.1 Sender & Deliverability",
                check="Reply-to is a monitored inbox (not noreply@)",
                status="fail" if is_noreply else "pass",
                issue=(
                    f"Reply-to '{reply_to}' is a no-reply address. Use a monitored inbox."
                    if is_noreply
                    else ""
                ),
                severity="high" if is_noreply else "info",
                fix="Change reply-to to a monitored inbox (e.g. events@linuxfoundation.org)",
            )
        )
    else:
        checks.append(
            QACheck(
                section="4.1 Sender & Deliverability",
                check="Reply-to configured",
                status="warn",
                issue="Reply-to address not set. Recipients who reply will write to the From address.",
                severity="medium",
                fix="Set a reply-to address to a monitored inbox.",
            )
        )

    # SPF/DKIM — can't verify programmatically; flag for manual check
    checks.append(
        QACheck(
            section="4.1 Sender & Deliverability",
            check="SPF/DKIM/DMARC alignment",
            status="info",
            issue=(
                "DNS authentication cannot be verified automatically. "
                "Confirm SPF, DKIM, and DMARC are configured for the sending domain in HubSpot."
            ),
            severity="info",
            deep_link=(
                f"https://app.hubspot.com/email/{portal_id}/settings/sending-domains"
                if portal_id
                else "https://app.hubspot.com → Email → Settings → Sending Domains"
            ),
        )
    )
    manual_actions.append("Confirm SPF/DKIM/DMARC alignment for the sending domain.")

    # ── 4.2 Subscription & Preference Center ────────────────────────────────

    checks.append(
        QACheck(
            section="4.2 Subscription & Preference Center",
            check="Correct subscription type assigned",
            status="pass" if subscription_type_id else "fail",
            issue="" if subscription_type_id else "No subscription type assigned to this email.",
            severity="critical" if not subscription_type_id else "info",
            fix=(
                "Use list_hubspot_subscription_types to get valid IDs, confirm with user, "
                "then assign before creating the draft."
                if not subscription_type_id
                else ""
            ),
        )
    )

    # Unsubscribe link
    has_unsub = any(
        kw in body_html.lower()
        for kw in ["unsubscribe", "opt-out", "opt out", "subscription preferences", "manage preferences"]
    )
    checks.append(
        QACheck(
            section="4.2 Subscription & Preference Center",
            check="Unsubscribe link present",
            status="pass" if has_unsub else "fail",
            issue=(
                ""
                if has_unsub
                else "No unsubscribe link detected — required by CAN-SPAM, GDPR, and CASL."
            ),
            severity="critical" if not has_unsub else "info",
            fix=(
                "Add HubSpot unsubscribe token {{ unsubscribe_link }} to the email footer."
                if not has_unsub
                else ""
            ),
        )
    )
    if not has_unsub:
        claude_can_fix.append("Add {{ unsubscribe_link }} token to the email footer.")

    # Physical address
    has_address = any(
        kw in body_html.lower()
        for kw in ["suite", "floor", "ave", "avenue", "street", "st.", "p.o. box"]
    ) or __import__("re").search(r"\b\d{5}(?:-\d{4})?\b", body_html)

    checks.append(
        QACheck(
            section="4.2 Subscription & Preference Center",
            check="Physical mailing address in footer",
            status="pass" if has_address else "warn",
            issue=(
                ""
                if has_address
                else "No physical mailing address detected — required by CAN-SPAM."
            ),
            severity="medium" if not has_address else "info",
            fix="Add the organization's physical address to the email footer." if not has_address else "",
        )
    )

    # Suppression lists
    has_suppressions = bool(suppression_list_ids)
    checks.append(
        QACheck(
            section="4.2 Subscription & Preference Center",
            check="Suppression lists applied (global opt-outs, bounces, GDPR)",
            status="pass" if has_suppressions else "warn",
            issue=(
                ""
                if has_suppressions
                else (
                    "No suppression lists specified. Confirm global opt-outs, bounce list, "
                    "and GDPR suppression list are excluded."
                )
            ),
            severity="high" if not has_suppressions else "info",
            deep_link=(
                f"https://app.hubspot.com/contacts/{portal_id}/objectLists"
                if portal_id
                else ""
            ),
        )
    )
    if not has_suppressions:
        manual_actions.append(
            "Apply suppression lists: global opt-outs, bounce list, GDPR suppression list."
        )

    # ── 4.3 Consent Compliance ───────────────────────────────────────────────

    # Audience list health checks
    if audience_lists:
        for lst in audience_lists:
            list_size = lst.get("size", -1)
            list_name = lst.get("name", lst.get("id", "unknown"))
            list_type = lst.get("listType", "")

            if list_size == 0:
                checks.append(
                    QACheck(
                        section="4.3 Consent Compliance",
                        check=f"Audience list size: {list_name}",
                        status="fail",
                        issue=f"List '{list_name}' has 0 contacts — do not send to an empty list.",
                        severity="critical",
                        fix="Verify the list definition or choose the correct list.",
                    )
                )
            elif list_size != -1 and list_size < 10:
                checks.append(
                    QACheck(
                        section="4.3 Consent Compliance",
                        check=f"Audience list size: {list_name}",
                        status="warn",
                        issue=f"List '{list_name}' has only {list_size} contacts — unusually low.",
                        severity="medium",
                    )
                )
            else:
                checks.append(
                    QACheck(
                        section="4.3 Consent Compliance",
                        check=f"Audience list size: {list_name}",
                        status="pass",
                    )
                )

            if list_type == "STATIC":
                checks.append(
                    QACheck(
                        section="4.3 Consent Compliance",
                        check=f"List type: {list_name}",
                        status="warn",
                        issue=(
                            f"'{list_name}' is a STATIC list — verify it was recently updated "
                            "and reflects current consent."
                        ),
                        severity="medium",
                    )
                )
    else:
        checks.append(
            QACheck(
                section="4.3 Consent Compliance",
                check="Audience list health",
                status="info",
                issue="No audience list data provided — use validate_audience_lists to check list health.",
                severity="info",
            )
        )

    # EU/CA consent — can't verify without CRM data; flag for human review
    checks.append(
        QACheck(
            section="4.3 Consent Compliance",
            check="EU GDPR consent for EU contacts",
            status="info",
            issue=(
                "GDPR consent cannot be verified automatically. Confirm EU contacts in the "
                "audience list have documented opt-in with source + timestamp."
            ),
            severity="info",
        )
    )
    checks.append(
        QACheck(
            section="4.3 Consent Compliance",
            check="CA CASL consent for Canadian contacts",
            status="info",
            issue=(
                "CASL consent cannot be verified automatically. Confirm CA contacts have express "
                "consent ≤2 years old (or implied consent ≤6 months for inquiries)."
            ),
            severity="info",
        )
    )
    manual_actions.append("Manually confirm GDPR/CASL consent coverage before sending to EU/CA contacts.")

    # ── 4.4 Content QA ──────────────────────────────────────────────────────

    # Subject line
    subject_issues = validate_subject_line(subject)
    if subject_issues:
        for si in subject_issues:
            checks.append(
                QACheck(
                    section="4.4 Content QA",
                    check="Subject line quality",
                    status="fail" if si["severity"] in ("high", "critical") else "warn",
                    issue=si["issue"],
                    severity=si["severity"],
                )
            )
    else:
        checks.append(
            QACheck(section="4.4 Content QA", check="Subject line quality", status="pass")
        )

    # Preheader
    preheader_issues = validate_preheader(subject, preheader)
    if preheader_issues:
        for pi in preheader_issues:
            checks.append(
                QACheck(
                    section="4.4 Content QA",
                    check="Preheader",
                    status="warn",
                    issue=pi["issue"],
                    severity=pi["severity"],
                )
            )
    else:
        checks.append(QACheck(section="4.4 Content QA", check="Preheader", status="pass"))

    # UTM links
    utm_spec_raw = draft.get("utm_spec")
    utm_spec = None
    if utm_spec_raw:
        from .utm_tagger import UtmSpec
        utm_spec = UtmSpec(**utm_spec_raw)

    link_audits = audit_all_links(body_html, utm_spec) if body_html else []
    broken_links = [a for a in link_audits if "Placeholder" in a.get("issue", "")]
    missing_utm_links = [
        a for a in link_audits
        if not a["has_utm"] and "Placeholder" not in a.get("issue", "")
    ]

    if broken_links:
        for bl in broken_links:
            checks.append(
                QACheck(
                    section="4.4 Content QA",
                    check="No broken/placeholder links",
                    status="fail",
                    issue=f"Broken link: {bl['url']}",
                    severity="high",
                    fix="Replace placeholder with the actual destination URL.",
                )
            )
    else:
        checks.append(
            QACheck(section="4.4 Content QA", check="No broken/placeholder links", status="pass")
        )

    if missing_utm_links:
        corrected = [a for a in missing_utm_links if a.get("corrected_url")]
        checks.append(
            QACheck(
                section="4.4 Content QA",
                check="UTM parameters on all outbound links",
                status="warn",
                issue=f"{len(missing_utm_links)} link(s) missing UTM parameters.",
                severity="medium",
                fix=(
                    "Corrected URLs generated — apply them to the email body."
                    if corrected
                    else "Add utm_source, utm_medium, utm_campaign, utm_content to each link."
                ),
            )
        )
        if corrected:
            claude_can_fix.append(
                f"Apply corrected UTM URLs to {len(corrected)} link(s) in the email body."
            )
    else:
        checks.append(
            QACheck(
                section="4.4 Content QA",
                check="UTM parameters on all outbound links",
                status="pass",
            )
        )

    # Personalization token fallbacks
    import re as _re
    bad_tokens = _re.findall(r"\{\{\s*contact\.\w+\s*\}\}", body_html)
    if bad_tokens:
        checks.append(
            QACheck(
                section="4.4 Content QA",
                check="Personalization tokens have fallback values",
                status="fail",
                issue=f"Tokens without fallback: {', '.join(set(bad_tokens))}",
                severity="high",
                fix="Add | default: 'there' (or appropriate fallback) to each token.",
            )
        )
        claude_can_fix.append("Add fallback values to personalization tokens.")
    else:
        checks.append(
            QACheck(
                section="4.4 Content QA",
                check="Personalization tokens have fallback values",
                status="pass",
            )
        )

    # ── 4.5 Sense Check ─────────────────────────────────────────────────────

    # Single CTA check (heuristic: count <a> tags with btn/button/cta in class or text)
    cta_pattern = _re.compile(
        r'<a[^>]+(?:class=["\'][^"\']*(?:btn|button|cta)[^"\']*["\'])[^>]*>',
        _re.IGNORECASE,
    )
    cta_matches = cta_pattern.findall(body_html)
    if len(cta_matches) > 1:
        checks.append(
            QACheck(
                section="4.5 Sense Check",
                check="Single primary CTA",
                status="warn",
                issue=f"Detected {len(cta_matches)} CTA button(s). Use one primary CTA to avoid diluting click-through.",
                severity="low",
            )
        )
    else:
        checks.append(
            QACheck(section="4.5 Sense Check", check="Single primary CTA", status="pass")
        )

    # Subject / content alignment (heuristic: key words from subject appear in body)
    subject_words = set(_re.findall(r"\b\w{5,}\b", subject.lower()))
    body_text = _re.sub(r"<[^>]+>", " ", body_html).lower()
    overlap = subject_words & set(_re.findall(r"\b\w{5,}\b", body_text))
    if subject_words and len(overlap) < max(1, len(subject_words) // 3):
        checks.append(
            QACheck(
                section="4.5 Sense Check",
                check="Subject line reflects email content",
                status="warn",
                issue=(
                    "Subject line words don't strongly overlap with the email body. "
                    "Verify the subject accurately describes the email content."
                ),
                severity="low",
            )
        )
    else:
        checks.append(
            QACheck(
                section="4.5 Sense Check",
                check="Subject line reflects email content",
                status="pass",
            )
        )

    # Build report
    verdict = _verdict_from_checks(checks)
    fail_count = sum(1 for c in checks if c.status == "fail")
    warn_count = sum(1 for c in checks if c.status == "warn")

    if verdict == "BLOCKED":
        summary = f"BLOCKED — {fail_count} critical/high issue(s) must be resolved before this email can be created."
    elif verdict == "NEEDS_CHANGES":
        summary = f"NEEDS CHANGES — {fail_count + warn_count} issue(s) to address before sending."
    else:
        summary = "READY TO SEND — all checks passed."

    return QAReport(
        checks=checks,
        verdict=verdict,
        summary=summary,
        claude_can_fix=claude_can_fix,
        manual_actions=manual_actions,
    )
