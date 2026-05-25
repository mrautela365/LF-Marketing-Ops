"""Tests for qa_runner.py"""

import pytest

from src.lib.qa_runner import QACheck, QAReport, Verdict, run_qa, _verdict_from_checks


CLEAN_DRAFT = {
    "name": "26Q2 - LF Events - OSS India 2026",
    "subject": "Join us at OSS India 2026",
    "preheader": "Early bird pricing ends June 1 — save your seat.",
    "from_name": "LF Events",
    "from_email": "events@linuxfoundation.org",
    "reply_to": "events@linuxfoundation.org",
    "body_html": (
        "<p>Hi {{ contact.firstname | default: 'there' }},</p>"
        "<a href='https://events.lf.org/register?utm_source=hubspot&utm_medium=email&utm_campaign=26q2-oss-india-2026&utm_content=cta'>Register</a>"
        "<p><a href='{{ unsubscribe_link }}'>Unsubscribe</a></p>"
        "<p>Linux Foundation, 1 Letterman Dr, San Francisco CA 94129</p>"
    ),
    "subscription_type_id": "12345",
    "audience_list_ids": [],
    "suppression_list_ids": [],
}


# ── _verdict_from_checks ──────────────────────────────────────────────────────

class TestVerdictFromChecks:
    def test_all_pass_returns_ready(self):
        checks = [QACheck(section="s", check="c", status="pass")]
        assert _verdict_from_checks(checks) == "READY_TO_SEND"

    def test_critical_fail_returns_blocked(self):
        checks = [QACheck(section="s", check="c", status="fail", severity="critical")]
        assert _verdict_from_checks(checks) == "BLOCKED"

    def test_high_fail_returns_needs_changes(self):
        checks = [QACheck(section="s", check="c", status="fail", severity="high")]
        assert _verdict_from_checks(checks) == "NEEDS_CHANGES"

    def test_medium_warn_returns_needs_changes(self):
        checks = [QACheck(section="s", check="c", status="warn", severity="medium")]
        assert _verdict_from_checks(checks) == "NEEDS_CHANGES"

    def test_only_info_returns_ready(self):
        checks = [QACheck(section="s", check="c", status="info", severity="info")]
        assert _verdict_from_checks(checks) == "READY_TO_SEND"


# ── run_qa ────────────────────────────────────────────────────────────────────

class TestRunQa:
    def test_clean_draft_passes_all_checks(self):
        report = run_qa(CLEAN_DRAFT)
        # Should be READY or NEEDS_CHANGES (DNS checks are info-only)
        assert report.verdict in ("READY_TO_SEND", "NEEDS_CHANGES")
        # No critical or high failures
        blockers = [c for c in report.checks if c.status == "fail" and c.severity in ("critical", "high")]
        assert len(blockers) == 0

    def test_missing_subscription_type_blocks(self):
        draft = {**CLEAN_DRAFT, "subscription_type_id": ""}
        report = run_qa(draft)
        assert report.verdict == "BLOCKED"
        assert any("subscription" in c.check.lower() and c.status == "fail" for c in report.checks)

    def test_missing_unsubscribe_blocks(self):
        draft = {**CLEAN_DRAFT, "body_html": "<p>Hello world with 123 Main St SF CA 94129</p>"}
        report = run_qa(draft)
        assert report.verdict == "BLOCKED"
        assert any("unsubscribe" in c.check.lower() and c.status == "fail" for c in report.checks)

    def test_freemail_from_causes_fail(self):
        draft = {**CLEAN_DRAFT, "from_email": "person@gmail.com"}
        report = run_qa(draft)
        assert any(c.status == "fail" and "brand domain" in c.check.lower() for c in report.checks)

    def test_noreply_reply_to_causes_fail(self):
        draft = {**CLEAN_DRAFT, "reply_to": "noreply@linuxfoundation.org"}
        report = run_qa(draft)
        assert any(c.status == "fail" and "monitored" in c.check.lower() for c in report.checks)

    def test_empty_audience_list_blocks(self):
        draft = {**CLEAN_DRAFT}
        audience_lists = [{"id": "123", "name": "My List", "listType": "ACTIVE", "size": 0}]
        report = run_qa(draft, audience_lists=audience_lists)
        assert any(c.status == "fail" and c.severity == "critical" for c in report.checks)

    def test_static_list_warns(self):
        draft = {**CLEAN_DRAFT}
        audience_lists = [{"id": "456", "name": "Static List", "listType": "STATIC", "size": 200}]
        report = run_qa(draft, audience_lists=audience_lists)
        assert any("static" in c.issue.lower() for c in report.checks)

    def test_missing_suppressions_warn(self):
        draft = {**CLEAN_DRAFT, "suppression_list_ids": []}
        report = run_qa(draft)
        assert any("suppression" in c.check.lower() and c.status in ("warn", "fail") for c in report.checks)

    def test_report_has_summary(self):
        report = run_qa(CLEAN_DRAFT)
        assert isinstance(report.summary, str) and len(report.summary) > 0

    def test_report_to_dict(self):
        report = run_qa(CLEAN_DRAFT)
        d = report.to_dict()
        assert "verdict" in d
        assert "checks" in d
        assert "claude_can_fix" in d
        assert "manual_actions" in d

    def test_token_without_fallback_flagged(self):
        draft = {
            **CLEAN_DRAFT,
            "body_html": (
                "<p>Hi {{ contact.firstname }},</p>"
                "<p><a href='{{ unsubscribe_link }}'>Unsubscribe</a></p>"
                "<p>123 Main St SF CA 94129</p>"
            ),
        }
        report = run_qa(draft)
        assert any("fallback" in c.issue.lower() for c in report.checks)
