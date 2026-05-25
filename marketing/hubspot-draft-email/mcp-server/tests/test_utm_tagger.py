"""Tests for utm_tagger.py"""

import pytest

from src.lib.utm_tagger import (
    UtmSpec,
    audit_all_links,
    audit_link,
    build_utm_url,
    check_spam_triggers,
    extract_links_from_html,
    validate_from_email,
    validate_preheader,
    validate_subject_line,
)


# ── build_utm_url ─────────────────────────────────────────────────────────────

class TestBuildUtmUrl:
    def test_adds_all_required_params(self):
        spec = UtmSpec(campaign="26q2-oss-india-2026", content="register-cta")
        url = build_utm_url("https://events.linuxfoundation.org/register", spec)
        assert "utm_source=hubspot" in url
        assert "utm_medium=email" in url
        assert "utm_campaign=26q2-oss-india-2026" in url
        assert "utm_content=register-cta" in url

    def test_replaces_existing_utm_params(self):
        base = "https://example.com/?utm_source=old&utm_campaign=old"
        spec = UtmSpec(campaign="new-campaign", content="cta")
        url = build_utm_url(base, spec)
        assert "utm_source=hubspot" in url
        assert "utm_campaign=new-campaign" in url
        assert "old" not in url

    def test_preserves_non_utm_query_params(self):
        spec = UtmSpec(campaign="26q2-test", content="cta")
        url = build_utm_url("https://example.com/?ref=newsletter", spec)
        assert "ref=newsletter" in url

    def test_adds_utm_term_when_provided(self):
        spec = UtmSpec(campaign="26q2-test", content="cta", term="india-attendees")
        url = build_utm_url("https://example.com/", spec)
        assert "utm_term=india-attendees" in url

    def test_no_utm_term_when_empty(self):
        spec = UtmSpec(campaign="26q2-test", content="cta", term="")
        url = build_utm_url("https://example.com/", spec)
        assert "utm_term" not in url


# ── extract_links_from_html ───────────────────────────────────────────────────

class TestExtractLinks:
    def test_extracts_http_links(self):
        html = '<a href="https://example.com/page">Click</a>'
        assert "https://example.com/page" in extract_links_from_html(html)

    def test_skips_mailto_and_anchors(self):
        html = '<a href="mailto:info@lf.org">Email</a> <a href="#section">Anchor</a>'
        links = extract_links_from_html(html)
        assert not any(l.startswith("mailto:") or l == "#section" for l in links)

    def test_deduplicates_links(self):
        html = '<a href="https://lf.org">A</a> <a href="https://lf.org">B</a>'
        links = extract_links_from_html(html)
        assert links.count("https://lf.org") == 1

    def test_skips_hubspot_tokens(self):
        html = '<a href="{{ unsubscribe_link }}">Unsubscribe</a>'
        links = extract_links_from_html(html)
        assert len(links) == 0


# ── audit_link ────────────────────────────────────────────────────────────────

class TestAuditLink:
    def test_pass_for_fully_tagged_url(self):
        url = "https://lf.org/?utm_source=hubspot&utm_medium=email&utm_campaign=test&utm_content=cta"
        result = audit_link(url)
        assert result.has_utm is True
        assert not result.missing_params

    def test_fail_for_untagged_url(self):
        url = "https://lf.org/register"
        result = audit_link(url)
        assert result.has_utm is False
        assert "utm_source" in result.missing_params

    def test_placeholder_url_flagged(self):
        result = audit_link("#")
        assert result.has_utm is False
        assert "Placeholder" in result.issue

    def test_corrected_url_generated_when_spec_provided(self):
        spec = UtmSpec(campaign="26q2-test", content="cta")
        result = audit_link("https://lf.org/register", spec)
        assert result.corrected_url != ""
        assert "utm_source=hubspot" in result.corrected_url


# ── validate_from_email ───────────────────────────────────────────────────────

class TestValidateFromEmail:
    def test_valid_brand_email(self):
        ok, reason = validate_from_email("events@linuxfoundation.org")
        assert ok is True

    def test_rejects_gmail(self):
        ok, reason = validate_from_email("person@gmail.com")
        assert ok is False
        assert "Freemail" in reason

    def test_rejects_role_based_info(self):
        ok, reason = validate_from_email("info@linuxfoundation.org")
        assert ok is False
        assert "Role-based" in reason

    def test_rejects_noreply(self):
        ok, reason = validate_from_email("noreply@linuxfoundation.org")
        assert ok is False

    def test_rejects_invalid_email(self):
        ok, reason = validate_from_email("notanemail")
        assert ok is False


# ── validate_subject_line ─────────────────────────────────────────────────────

class TestValidateSubjectLine:
    def test_valid_subject_no_issues(self):
        issues = validate_subject_line("Join us at OSS India 2026 — Early bird ends Friday")
        assert not any(i["severity"] in ("high", "critical") for i in issues)

    def test_flags_long_subject(self):
        issues = validate_subject_line("A" * 65)
        assert any("chars" in i["issue"] for i in issues)

    def test_flags_all_caps(self):
        issues = validate_subject_line("REGISTER NOW FOR FREE")
        assert any(i["severity"] == "high" for i in issues)

    def test_flags_spam_trigger(self):
        issues = validate_subject_line("guaranteed results with our free offer")
        assert any(i["severity"] == "high" for i in issues)

    def test_flags_excessive_exclamation(self):
        issues = validate_subject_line("Register now!!!")
        assert any("exclamation" in i["issue"].lower() for i in issues)


# ── validate_preheader ────────────────────────────────────────────────────────

class TestValidatePreheader:
    def test_empty_preheader_flagged(self):
        issues = validate_preheader("Subject line", "")
        assert any("empty" in i["issue"].lower() for i in issues)

    def test_preheader_repeating_subject_flagged(self):
        issues = validate_preheader("Join us at OSS India", "Join us at OSS India")
        assert any("repeats" in i["issue"].lower() for i in issues)

    def test_long_preheader_flagged(self):
        issues = validate_preheader("Subject", "P" * 110)
        assert any("chars" in i["issue"] for i in issues)

    def test_good_preheader_no_issues(self):
        issues = validate_preheader(
            "Join us at OSS India 2026",
            "Early bird pricing ends June 1 — save your seat now."
        )
        assert len(issues) == 0


# ── check_spam_triggers ───────────────────────────────────────────────────────

class TestCheckSpamTriggers:
    def test_detects_free(self):
        assert "free" in check_spam_triggers("Get your free ticket")

    def test_case_insensitive(self):
        assert "guaranteed" in check_spam_triggers("GUARANTEED results")

    def test_clean_text_returns_empty(self):
        assert check_spam_triggers("Join us at the conference in Hyderabad") == []
