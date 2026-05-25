"""Tests for email_builder.py"""

import pytest

from src.lib.email_builder import (
    _has_physical_address,
    _has_unsubscribe_link,
    _tokens_without_fallback,
    build_email_payload,
    validate_draft_spec,
)


VALID_SPEC = {
    "name": "26Q2 - LF Events - OSS India 2026",
    "subject": "Join us at OSS India 2026",
    "preheader": "Early bird pricing ends June 1.",
    "from_name": "LF Events",
    "from_email": "events@linuxfoundation.org",
    "reply_to": "events@linuxfoundation.org",
    "body_html": (
        "<p>Hi {{ contact.firstname | default: 'there' }},</p>"
        "<a href='https://events.lf.org/register?utm_source=hubspot&utm_medium=email&utm_campaign=test&utm_content=cta'>Register</a>"
        "<p><a href='{{ unsubscribe_link }}'>Unsubscribe</a></p>"
        "<p>Linux Foundation, 1 Letterman Dr, San Francisco CA 94129</p>"
    ),
    "subscription_type_id": "12345",
}


# ── validate_draft_spec ───────────────────────────────────────────────────────

class TestValidateDraftSpec:
    def test_valid_spec_returns_no_critical_issues(self):
        issues = validate_draft_spec(VALID_SPEC)
        critical = [i for i in issues if i["severity"] == "critical"]
        assert not critical

    def test_missing_name_is_critical(self):
        spec = {**VALID_SPEC, "name": ""}
        issues = validate_draft_spec(spec)
        assert any(i["field"] == "name" and i["severity"] == "critical" for i in issues)

    def test_missing_subject_is_critical(self):
        spec = {**VALID_SPEC, "subject": ""}
        issues = validate_draft_spec(spec)
        assert any(i["field"] == "subject" and i["severity"] == "critical" for i in issues)

    def test_missing_subscription_type_is_critical(self):
        spec = {**VALID_SPEC, "subscription_type_id": ""}
        issues = validate_draft_spec(spec)
        assert any(i["field"] == "subscription_type_id" and i["severity"] == "critical" for i in issues)

    def test_freemail_from_is_high(self):
        spec = {**VALID_SPEC, "from_email": "person@gmail.com"}
        issues = validate_draft_spec(spec)
        assert any(i["field"] == "from_email" and i["severity"] == "high" for i in issues)

    def test_noreply_reply_to_is_high(self):
        spec = {**VALID_SPEC, "reply_to": "noreply@linuxfoundation.org"}
        issues = validate_draft_spec(spec)
        assert any(i["field"] == "reply_to" and i["severity"] == "high" for i in issues)

    def test_missing_unsubscribe_link_is_high(self):
        spec = {**VALID_SPEC, "body_html": "<p>Hello world</p><p>123 Main St</p>"}
        issues = validate_draft_spec(spec)
        assert any("unsubscribe" in i["issue"].lower() and i["severity"] == "high" for i in issues)

    def test_token_without_fallback_is_high(self):
        spec = {**VALID_SPEC, "body_html": "<p>Hi {{ contact.firstname }}</p><p><a href='{{ unsubscribe_link }}'>Unsub</a></p><p>123 Main St</p>"}
        issues = validate_draft_spec(spec)
        assert any("fallback" in i["issue"].lower() and i["severity"] == "high" for i in issues)


# ── _has_unsubscribe_link ─────────────────────────────────────────────────────

class TestHasUnsubscribeLink:
    def test_detects_unsubscribe_text(self):
        assert _has_unsubscribe_link("<a href='#'>Unsubscribe</a>") is True

    def test_detects_opt_out(self):
        assert _has_unsubscribe_link("<p>Click here to opt-out</p>") is True

    def test_detects_subscription_preferences(self):
        assert _has_unsubscribe_link("<a href='...'>Manage subscription preferences</a>") is True

    def test_missing_returns_false(self):
        assert _has_unsubscribe_link("<p>Hello world</p>") is False


# ── _has_physical_address ─────────────────────────────────────────────────────

class TestHasPhysicalAddress:
    def test_detects_suite_keyword(self):
        assert _has_physical_address("<p>1 Letterman Dr, Suite 100</p>") is True

    def test_detects_zip_code(self):
        assert _has_physical_address("<p>San Francisco CA 94129</p>") is True

    def test_missing_returns_false(self):
        assert _has_physical_address("<p>Hello world</p>") is False


# ── _tokens_without_fallback ──────────────────────────────────────────────────

class TestTokensWithoutFallback:
    def test_detects_bare_token(self):
        result = _tokens_without_fallback("Hi {{ contact.firstname }}")
        assert len(result) == 1

    def test_token_with_fallback_not_flagged(self):
        result = _tokens_without_fallback("Hi {{ contact.firstname | default: 'there' }}")
        assert len(result) == 0

    def test_mixed_tokens(self):
        html = "Hi {{ contact.firstname }} from {{ contact.company | default: 'your company' }}"
        result = _tokens_without_fallback(html)
        assert len(result) == 1
        assert "contact.firstname" in result[0]


# ── build_email_payload ───────────────────────────────────────────────────────

class TestBuildEmailPayload:
    def test_maps_required_fields(self):
        payload = build_email_payload(VALID_SPEC)
        assert payload["name"] == VALID_SPEC["name"]
        assert payload["subject"] == VALID_SPEC["subject"]
        assert payload["fromName"] == VALID_SPEC["from_name"]
        assert payload["fromEmail"] == VALID_SPEC["from_email"]

    def test_never_auto_sends(self):
        payload = build_email_payload(VALID_SPEC)
        assert payload["sendOnPublish"] is False

    def test_includes_subscription_id(self):
        payload = build_email_payload(VALID_SPEC)
        assert payload["subscriptionId"] == VALID_SPEC["subscription_type_id"]

    def test_preheader_mapped_to_preview_text(self):
        payload = build_email_payload(VALID_SPEC)
        assert payload["previewText"] == VALID_SPEC["preheader"]

    def test_no_scheduled_at_by_default(self):
        payload = build_email_payload(VALID_SPEC)
        assert "scheduledAt" not in payload

    def test_scheduled_at_included_when_set(self):
        spec = {**VALID_SPEC, "scheduled_at": "2026-06-15T14:00:00Z"}
        payload = build_email_payload(spec)
        assert payload["scheduledAt"] == "2026-06-15T14:00:00Z"
