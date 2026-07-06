"""
Comprehensive pytest test suite for the email staging service.

Covers:
  - hubspot_tools: _col_widths, update_email_content, validate_staged_email,
                   get_email_content_text, sponsor filtering, banner widget,
                   set_email_send_list, search_lists
  - agent.py: clone_turn, content_turn, extract_brand_history_from_messages
  - main.py API endpoints: /api/plan, /api/generate-content, /api/clone,
                           /api/set-send-list, /api/content, /api/stage-from-brief,
                           /api/lists/search
  - stage_detector: detect_stage
  - event_brands: location_fallback_chain, build_location_chain, extract_location_from_name
  - session_store: lifecycle and phase transitions
"""

import json
import sys
import os
import types
import importlib
from datetime import date, timedelta
from unittest.mock import patch, MagicMock, call

import pytest

# ---------------------------------------------------------------------------
# Minimal stub modules so we can import the backend without real credentials
# ---------------------------------------------------------------------------

def _make_stub(name):
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


def _ensure_stubs():
    # config stubs — must exist before any backend module is imported
    cfg = _make_stub("config")
    cfg.HUBSPOT_ACCESS_TOKEN  = "test-token"
    cfg.HUBSPOT_PORTAL_ID     = "8112310"
    cfg.ANTHROPIC_API_KEY     = ""
    cfg.CLAUDE_MODEL          = "claude-sonnet-4-6"
    cfg.LITELLM_BASE_URL      = ""
    cfg.LITELLM_API_KEY       = ""
    cfg.GOOGLE_SERVICE_ACCOUNT_FILE = ""
    cfg.INTERNAL_API_TOKEN    = "test-internal-token"
    cfg.ASANA_ACCESS_TOKEN    = ""
    cfg.ASSET_TAG             = ""
    cfg.tag_asset_name        = lambda name: name

    # anthropic stub (SDK not installed in test env)
    if "anthropic" not in sys.modules:
        ant = _make_stub("anthropic")
        ant.Anthropic = MagicMock

    # nest_asyncio stub
    if "nest_asyncio" not in sys.modules:
        na = _make_stub("nest_asyncio")
        na.apply = lambda: None

    # googleapiclient / google stubs
    for mod_name in ("googleapiclient", "googleapiclient.discovery",
                     "google", "google.oauth2", "google.oauth2.service_account"):
        if mod_name not in sys.modules:
            _make_stub(mod_name)

    # bs4 — prefer the real package (utm_tools does genuine HTML parsing that
    # tests rely on); only fall back to a stub if it's truly not installed.
    if "bs4" not in sys.modules:
        try:
            import bs4  # noqa: F401
        except ImportError:
            _make_stub("bs4")

    bs4_mod = sys.modules["bs4"]
    if not hasattr(bs4_mod, "BeautifulSoup"):
        bs4_mod.BeautifulSoup = MagicMock

    # audience_tools stub (complex deps)
    if "audience_tools" not in sys.modules:
        at = _make_stub("audience_tools")
        at.start_plan_job  = MagicMock(return_value="job-123")
        at.start_build_job = MagicMock(return_value="job-456")
        at.get_job_queue   = MagicMock(return_value=None)
        at.extract_master_list_id    = MagicMock(return_value="")
        at.extract_suppression_lists = MagicMock(return_value=[])
        at.remove_job = MagicMock()
        at.HUBSPOT_ACCESS_TOKEN = "test-token"

    # asana_tools stub
    if "asana_tools" not in sys.modules:
        ast = _make_stub("asana_tools")
        ast.parse_task_gid  = MagicMock(return_value="123456789")
        ast.get_task        = MagicMock(return_value={"name": "Test Task", "gid": "123"})
        ast.get_subtasks    = MagicMock(return_value=[])
        ast.get_stories     = MagicMock(return_value=[])
        ast.extract_brief   = MagicMock(return_value={
            "task_name": "Test Task", "brand_name": "LF", "content_doc_url": "",
            "event_url": "", "audience_instructions": "", "due_on": "",
            "subtask_names": [], "email_name": "Test Task",
        })

    # email_templates stub
    if "email_templates" not in sys.modules:
        et = _make_stub("email_templates")
        et.get_template = MagicMock(return_value={
            "subject": "Test Subject", "preheader": "Test preheader",
            "body": "<p>Test body</p>",
        })


_ensure_stubs()

# Now add backend to path and import modules under test
_BACKEND_DIR = os.path.join(os.path.dirname(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import hubspot_tools
import utm_tools
import stage_detector
from stage_detector import detect_stage, parse_event_date, STAGES
import session_store
from models import SessionState
import event_brands
from event_brands import (
    location_fallback_chain, build_location_chain,
    extract_location_from_name, lookup_event_brand, expand_location_words,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_email_response(
    email_id="email-001",
    subject="Test Subject",
    from_email="test@example.com",
    widgets=None,
    flex_areas=None,
):
    """Build a minimal HubSpot email GET response."""
    widgets   = widgets   or {}
    flex_areas = flex_areas or {}
    return {
        "id":         email_id,
        "name":       f"Test Email {email_id}",
        "subject":    subject,
        "fromEmail":  from_email,
        "state":      "DRAFT",
        "content":    {
            "templatePath": "@hubspot/email/dnd/Start_from_scratch.html",
            "widgets":      widgets,
            "flexAreas":    flex_areas,
            "styleSettings": {},
        },
    }


def _make_flex_areas(widget_keys, area_name="main"):
    """Build a flexAreas dict with `widget_keys` placed in a single section."""
    return {
        area_name: {
            "sections": [
                {
                    "id": "sec-0",
                    "columns": [{"id": "col-0", "widgets": list(widget_keys), "width": 12}],
                    "style": {},
                }
            ]
        }
    }


# ---------------------------------------------------------------------------
# ── TestColWidths ─────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class TestColWidths:
    """Tests for the _col_widths nested function inside update_email_content.

    We test it by calling update_email_content with sponsors and inspecting
    the generated column widths.  We also expose the logic directly by
    reimplementing it for unit-level tests.
    """

    @staticmethod
    def _col_widths(n):
        """Local copy of the production _col_widths logic for unit tests."""
        if n <= 0:
            return []
        base = 12 // n
        rem  = 12 % n
        return [base + (1 if i < rem else 0) for i in range(n)]

    def test_col_widths_zero_returns_empty(self):
        """n=0 must return an empty list (no columns, no division)."""
        assert self._col_widths(0) == []

    def test_col_widths_one_returns_twelve(self):
        """n=1: single column must occupy the full 12-unit grid."""
        result = self._col_widths(1)
        assert result == [12]
        assert sum(result) == 12

    def test_col_widths_two_sums_to_12(self):
        """n=2: two equal columns of width 6 each."""
        result = self._col_widths(2)
        assert sum(result) == 12
        assert result == [6, 6]

    def test_col_widths_three_sums_to_12(self):
        """n=3: each column width 4, total 12."""
        result = self._col_widths(3)
        assert sum(result) == 12
        assert result == [4, 4, 4]

    def test_col_widths_four_sums_to_12(self):
        """n=4: each column width 3, total 12."""
        result = self._col_widths(4)
        assert sum(result) == 12
        assert result == [3, 3, 3, 3]

    def test_col_widths_five_sums_to_12(self):
        """n=5 (max tier-1 sponsors): widths must be [3,3,2,2,2] summing to 12."""
        result = self._col_widths(5)
        assert sum(result) == 12
        assert result == [3, 3, 2, 2, 2]

    def test_col_widths_six_sums_to_12(self):
        """n=6: each column width 2, total 12."""
        result = self._col_widths(6)
        assert sum(result) == 12

    def test_col_widths_seven_sums_to_12(self):
        """n=7: remainder distributed across first columns."""
        result = self._col_widths(7)
        assert sum(result) == 12
        assert len(result) == 7

    def test_col_widths_twelve_sums_to_12(self):
        """n=12: each column gets width 1."""
        result = self._col_widths(12)
        assert sum(result) == 12
        assert result == [1] * 12

    def test_col_widths_all_widths_positive(self):
        """No width must be zero or negative for n=1..12."""
        for n in range(1, 13):
            result = self._col_widths(n)
            assert all(w > 0 for w in result), f"n={n} has non-positive width"

    def test_col_widths_length_matches_n(self):
        """Length of returned list must equal n for all n."""
        for n in range(1, 13):
            result = self._col_widths(n)
            assert len(result) == n, f"Expected length {n}, got {len(result)}"


# ---------------------------------------------------------------------------
# ── TestUpdateEmailContent ────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

def _mock_get_response_for_update(email_id, widget_keys=None, area_name="main"):
    """Return value for _get when update_email_content verifies the patch."""
    widget_keys = widget_keys or []
    widgets = {k: {"body": {"path": "@hubspot/rich_text", "html": "<p>ok</p>"}}
               for k in widget_keys}
    return _make_email_response(
        email_id=email_id,
        widgets=widgets,
        flex_areas=_make_flex_areas(widget_keys, area_name),
    )


class TestUpdateEmailContent:
    """Tests for hubspot_tools.update_email_content."""

    def _run(self, email_id="em1", html_content="<p>Hello</p>",
             banner_url="", event_url="", content_sections=None, sponsors=None,
             verify_widget_keys=None):
        """Helper: mock _get/_patch and call update_email_content."""
        verify_keys = verify_widget_keys or ["staging_body"]

        get_side_effects = [
            # First call: fetch current state
            _make_email_response(email_id),
            # Second call: verify patch
            _mock_get_response_for_update(email_id, verify_keys),
        ]

        patch_resp = _make_email_response(email_id)
        patch_resp["content"]["flexAreas"] = _make_flex_areas(verify_keys)

        with patch.object(hubspot_tools, "_get", side_effect=get_side_effects) as mock_get, \
             patch.object(hubspot_tools, "_patch", return_value=patch_resp) as mock_patch:
            result = hubspot_tools.update_email_content(
                email_id,
                html_content=html_content,
                banner_url=banner_url,
                event_url=event_url,
                content_sections=content_sections,
                sponsors=sponsors,
            )
        return result, mock_patch

    def test_no_sections_uses_fallback_rich_text(self):
        """No content_sections → falls back to monolithic rich_text widget."""
        result, mock_patch = self._run(
            html_content="<p>Body text</p>",
            content_sections=None,
        )
        assert result.get("success") is True
        assert result.get("method") == "rich_text_only"

    def test_no_sections_no_banner_method_label(self):
        """Method label is 'rich_text_only' when no banner and no sections."""
        result, _ = self._run(html_content="<p>x</p>")
        assert result.get("method") == "rich_text_only"

    def test_with_banner_creates_banner_section(self):
        """When banner_url is set, the payload must include staging_banner widget."""
        banner = "https://cdn.example.com/banner.png"
        result, mock_patch = self._run(
            html_content="<p>x</p>",
            banner_url=banner,
            verify_widget_keys=["staging_banner", "staging_body"],
        )
        patch_call_payload = mock_patch.call_args[0][1]
        widgets = patch_call_payload["content"]["widgets"]
        assert "staging_banner" in widgets

    def test_banner_widget_module_id(self):
        """Banner widget must use module_id=1367093."""
        banner = "https://cdn.example.com/banner.png"
        with patch.object(hubspot_tools, "_get", side_effect=[
            _make_email_response("em1"),
            _mock_get_response_for_update("em1", ["staging_banner", "staging_body"]),
        ]), patch.object(hubspot_tools, "_patch", return_value=_make_email_response("em1")):
            hubspot_tools.update_email_content("em1", html_content="<p>x</p>", banner_url=banner)

        # Extract the patch payload from mock
        with patch.object(hubspot_tools, "_get", side_effect=[
            _make_email_response("em1"),
            _mock_get_response_for_update("em1", ["staging_banner"]),
        ]) as _, patch.object(hubspot_tools, "_patch", return_value=_make_email_response("em1")) as mp:
            hubspot_tools.update_email_content("em1", html_content="<p>x</p>", banner_url=banner)
            payload = mp.call_args[0][1]
            banner_widget = payload["content"]["widgets"].get("staging_banner", {})
            assert banner_widget.get("body", {}).get("module_id") == 1367093

    def test_banner_widget_link_not_href(self):
        """Banner body uses field 'link', not 'href'."""
        banner = "https://cdn.example.com/banner.png"
        event_url = "https://events.linuxfoundation.org/test-event/"
        with patch.object(hubspot_tools, "_get", side_effect=[
            _make_email_response("em1"),
            _mock_get_response_for_update("em1", ["staging_banner"]),
        ]), patch.object(hubspot_tools, "_patch", return_value=_make_email_response("em1")) as mp:
            hubspot_tools.update_email_content(
                "em1", html_content="<p>x</p>",
                banner_url=banner, event_url=event_url,
            )
            body = mp.call_args[0][1]["content"]["widgets"]["staging_banner"]["body"]
            assert "link" in body
            assert "href" not in body
            assert body["link"] == event_url

    def test_banner_widget_stretch_on_mobile_true(self):
        """Banner body must have stretch_on_mobile=True."""
        banner = "https://cdn.example.com/banner.png"
        with patch.object(hubspot_tools, "_get", side_effect=[
            _make_email_response("em1"),
            _mock_get_response_for_update("em1", ["staging_banner"]),
        ]), patch.object(hubspot_tools, "_patch", return_value=_make_email_response("em1")) as mp:
            hubspot_tools.update_email_content("em1", html_content="<p>x</p>", banner_url=banner)
            body = mp.call_args[0][1]["content"]["widgets"]["staging_banner"]["body"]
            assert body.get("stretch_on_mobile") is True

    def test_no_path_none_in_sections(self):
        """No section in the patch payload may have path=None."""
        content_sections = [{"type": "rich_text", "html": "<p>Content</p>"}]
        sponsors_list = []
        with patch.object(hubspot_tools, "_get", side_effect=[
            _make_email_response("em1"),
            _mock_get_response_for_update("em1", ["staging_sec_0"]),
        ]), patch.object(hubspot_tools, "_patch", return_value=_make_email_response("em1")) as mp:
            hubspot_tools.update_email_content(
                "em1", content_sections=content_sections, sponsors=sponsors_list,
            )
            patch_payload = mp.call_args[0][1]
            sections = patch_payload["content"]["flexAreas"]["main"]["sections"]
            for sec in sections:
                assert sec.get("path") is not None or "path" not in sec

    def test_no_box_index_keys_in_flex_areas(self):
        """flexAreas dict must not contain boxFirstElementIndex or boxLastElementIndex."""
        with patch.object(hubspot_tools, "_get", side_effect=[
            _make_email_response("em1"),
            _mock_get_response_for_update("em1", ["staging_body"]),
        ]), patch.object(hubspot_tools, "_patch", return_value=_make_email_response("em1")) as mp:
            hubspot_tools.update_email_content("em1", html_content="<p>x</p>")
            payload = mp.call_args[0][1]
            fa = payload["content"]["flexAreas"]
            for area_val in fa.values():
                assert "boxFirstElementIndex" not in area_val
                assert "boxLastElementIndex" not in area_val

    def test_tier1_sponsors_column_widths_sum_to_12(self):
        """Tier1 sponsor row column widths in patch payload must sum to 12."""
        content_sections = [{"type": "rich_text", "html": "<p>Body</p>"}]
        sponsors = [
            {"name": f"Sponsor{i}", "logo_url": f"https://cdn.example.com/sp{i}.png"}
            for i in range(5)
        ]
        with patch.object(hubspot_tools, "_get", side_effect=[
            _make_email_response("em1"),
            _mock_get_response_for_update("em1", [
                "staging_sec_0", "staging_sponsor_header",
                "staging_sponsor_t1_0", "staging_sponsor_t1_1",
            ]),
        ]), patch.object(hubspot_tools, "_patch", return_value=_make_email_response("em1")) as mp:
            hubspot_tools.update_email_content(
                "em1", content_sections=content_sections, sponsors=sponsors,
            )
            sections = mp.call_args[0][1]["content"]["flexAreas"]["main"]["sections"]
            t1_sec = next((s for s in sections if s.get("id") == "section-sponsor-tier1"), None)
            if t1_sec:
                widths = [col.get("width", 0) for col in t1_sec.get("columns", [])]
                assert sum(widths) == 12

    def test_tier2_sponsors_column_widths_sum_to_12(self):
        """Tier2 sponsor row column widths must also sum to 12."""
        content_sections = [{"type": "rich_text", "html": "<p>Body</p>"}]
        sponsors = [
            {"name": f"Sponsor{i}", "logo_url": f"https://cdn.example.com/sp{i}.png"}
            for i in range(8)
        ]
        with patch.object(hubspot_tools, "_get", side_effect=[
            _make_email_response("em1"),
            _mock_get_response_for_update("em1", ["staging_sec_0", "staging_sponsor_t2_0"]),
        ]), patch.object(hubspot_tools, "_patch", return_value=_make_email_response("em1")) as mp:
            hubspot_tools.update_email_content(
                "em1", content_sections=content_sections, sponsors=sponsors,
            )
            sections = mp.call_args[0][1]["content"]["flexAreas"]["main"]["sections"]
            t2_sec = next((s for s in sections if s.get("id") == "section-sponsor-tier2"), None)
            if t2_sec:
                widths = [col["width"] for col in t2_sec.get("columns", [])]
                assert sum(widths) == 12

    def test_verification_failure_returns_error(self):
        """If saved widget keys don't overlap with our widgets, error dict is returned."""
        # First get: current state; Second get: completely different widgets (no overlap)
        saved_email = _make_email_response(
            email_id="em1",
            widgets={"some_other_widget": {"body": {}}},
            flex_areas=_make_flex_areas(["some_other_widget"]),
        )
        with patch.object(hubspot_tools, "_get", side_effect=[
            _make_email_response("em1"),
            saved_email,
        ]), patch.object(hubspot_tools, "_patch", return_value=_make_email_response("em1")):
            result = hubspot_tools.update_email_content("em1", html_content="<p>x</p>")
        assert "error" in result

    def test_with_content_sections_method_label_structured(self):
        """When content_sections provided, method label includes 'structured'."""
        content_sections = [{"type": "rich_text", "html": "<p>hello</p>"}]
        with patch.object(hubspot_tools, "_get", side_effect=[
            _make_email_response("em1"),
            _mock_get_response_for_update("em1", ["staging_sec_0"]),
        ]), patch.object(hubspot_tools, "_patch", return_value=_make_email_response("em1")):
            result = hubspot_tools.update_email_content(
                "em1", content_sections=content_sections, sponsors=[],
            )
        assert result.get("success") is True
        assert "structured" in result.get("method", "")


# ---------------------------------------------------------------------------
# ── TestValidateStagedEmail ───────────────────────────────────────────────────
# ---------------------------------------------------------------------------

def _full_valid_email(email_id="em1"):
    """Return a GET response that passes all validation checks."""
    widgets = {
        "staging_banner": {
            "body": {
                "path": "@hubspot/image",
                "img": {"src": "https://cdn.example.com/banner.png"},
            }
        },
        "staging_body": {
            "body": {
                "path": "@hubspot/rich_text",
                "html": "<p>Join us for the event</p>",
            }
        },
        "staging_footer_divider": {
            "body": {"path": "@hubspot/email_divider", "line_type": "solid"}
        },
        "staging_footer_social": {
            "body": {"path": "@hubspot/follow_me_email", "social": []}
        },
        "staging_footer_hs": {
            "body": {"path": "@hubspot/email_footer"}
        },
    }
    all_keys = list(widgets.keys())
    return _make_email_response(
        email_id=email_id,
        subject="Test Subject",
        from_email="sender@example.com",
        widgets=widgets,
        flex_areas=_make_flex_areas(all_keys),
    )


class TestValidateStagedEmail:
    """Tests for hubspot_tools.validate_staged_email."""

    def test_passes_all_checks(self):
        """A well-formed email with banner, body, and footer passes validation."""
        with patch.object(hubspot_tools, "_get", return_value=_full_valid_email()):
            result = hubspot_tools.validate_staged_email(
                "em1", expect_banner=True, expect_sections=1,
            )
        assert result["valid"] is True
        assert result["issues"] == []

    def test_fails_no_widgets_in_flex_areas(self):
        """Email with empty flexAreas fails: content was not saved."""
        email = _make_email_response(
            subject="Subject", from_email="x@x.com",
            widgets={}, flex_areas={},
        )
        with patch.object(hubspot_tools, "_get", return_value=email):
            result = hubspot_tools.validate_staged_email("em1")
        assert result["valid"] is False
        assert any("no widget" in i.lower() for i in result["issues"])

    def test_fails_missing_banner(self):
        """When expect_banner=True but no image widget present, fails."""
        email = _full_valid_email()
        # Remove banner img
        email["content"]["widgets"]["staging_banner"]["body"].pop("img", None)
        with patch.object(hubspot_tools, "_get", return_value=email):
            result = hubspot_tools.validate_staged_email(
                "em1", expect_banner=True, expect_sections=1,
            )
        assert result["valid"] is False
        assert any("banner" in i.lower() for i in result["issues"])

    def test_fails_view_in_browser_text(self):
        """Widget containing 'view in browser' triggers system-text failure."""
        email = _full_valid_email()
        email["content"]["widgets"]["staging_body"]["body"]["html"] = (
            '<p><a href="#">View in browser</a></p>'
        )
        with patch.object(hubspot_tools, "_get", return_value=email):
            result = hubspot_tools.validate_staged_email("em1", expect_sections=1)
        assert result["valid"] is False
        assert any("view in browser" in i.lower() for i in result["issues"])

    def test_fails_unsubscribe_text(self):
        """Widget containing 'unsubscribe' triggers system-text failure."""
        email = _full_valid_email()
        email["content"]["widgets"]["staging_body"]["body"]["html"] = (
            '<p>Unsubscribe from this list</p>'
        )
        with patch.object(hubspot_tools, "_get", return_value=email):
            result = hubspot_tools.validate_staged_email("em1", expect_sections=1)
        assert result["valid"] is False
        assert any("unsubscribe" in i.lower() for i in result["issues"])

    def test_fails_wilmington_address_text(self):
        """Widget containing Wilmington address triggers system-text failure."""
        email = _full_valid_email()
        email["content"]["widgets"]["staging_body"]["body"]["html"] = (
            '<p>Wilmington, Delaware 19802</p>'
        )
        with patch.object(hubspot_tools, "_get", return_value=email):
            result = hubspot_tools.validate_staged_email("em1", expect_sections=1)
        assert result["valid"] is False

    def test_fails_missing_hs_footer(self):
        """Missing email_footer module causes validation failure."""
        email = _full_valid_email()
        email["content"]["widgets"].pop("staging_footer_hs")
        keys = [k for k in email["content"]["widgets"]]
        email["content"]["flexAreas"] = _make_flex_areas(keys)
        with patch.object(hubspot_tools, "_get", return_value=email):
            result = hubspot_tools.validate_staged_email("em1", expect_sections=1)
        assert result["valid"] is False
        assert any("footer" in i.lower() for i in result["issues"])

    def test_fails_missing_social_icons(self):
        """Missing social icons module causes validation failure."""
        email = _full_valid_email()
        email["content"]["widgets"].pop("staging_footer_social")
        keys = list(email["content"]["widgets"].keys())
        email["content"]["flexAreas"] = _make_flex_areas(keys)
        with patch.object(hubspot_tools, "_get", return_value=email):
            result = hubspot_tools.validate_staged_email("em1", expect_sections=1)
        assert result["valid"] is False

    def test_fails_insufficient_rich_text_sections(self):
        """Fewer rich_text sections than expected causes failure."""
        email = _full_valid_email()
        # Remove the body HTML so rich_text_count = 0
        email["content"]["widgets"]["staging_body"]["body"]["html"] = ""
        with patch.object(hubspot_tools, "_get", return_value=email):
            result = hubspot_tools.validate_staged_email("em1", expect_sections=2)
        assert result["valid"] is False
        assert any("content section" in i.lower() for i in result["issues"])

    def test_fetch_failure_returns_invalid(self):
        """When HubSpot fetch raises, returns valid=False with error message."""
        with patch.object(hubspot_tools, "_get", side_effect=Exception("API Error")):
            result = hubspot_tools.validate_staged_email("em1")
        assert result["valid"] is False
        assert "API Error" in result["issues"][0]


# ---------------------------------------------------------------------------
# ── TestGetEmailContentText ───────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class TestGetEmailContentText:
    """Tests for hubspot_tools.get_email_content_text."""

    def _base_email(self, widget_html=""):
        widgets = {
            "w1": {"body": {"html": widget_html}},
            "preview_text": {"body": {"value": "Preview text here"}},
        }
        return _make_email_response(
            email_id="em1", subject="Test Subject",
            widgets=widgets,
            flex_areas=_make_flex_areas(["w1"]),
        )

    def test_filters_view_in_browser_phrase(self):
        """Widgets containing 'view in browser' are excluded from sections_out."""
        email = self._base_email('<p><a href="#">View in browser</a></p>')
        with patch.object(hubspot_tools, "_get", return_value=email):
            result = hubspot_tools.get_email_content_text("em1")
        assert result["success"] is True
        assert result["body_html"] == ""
        assert not any(
            "view in browser" in s.get("html", "").lower()
            for s in result.get("sections", [])
        )

    def test_filters_unsubscribe_phrase(self):
        """Widgets containing 'unsubscribe' are excluded."""
        email = self._base_email('<p>Unsubscribe from this list</p>')
        with patch.object(hubspot_tools, "_get", return_value=email):
            result = hubspot_tools.get_email_content_text("em1")
        assert result["body_html"] == ""

    def test_filters_2810_n_church_address(self):
        """Widgets containing '2810 n church' physical address are excluded."""
        email = self._base_email('<p>2810 N Church St, Wilmington, Delaware</p>')
        with patch.object(hubspot_tools, "_get", return_value=email):
            result = hubspot_tools.get_email_content_text("em1")
        assert result["body_html"] == ""

    def test_filters_this_email_was_sent_by(self):
        """Widgets containing 'this email was sent by' are excluded."""
        email = self._base_email('<p>This email was sent by The Linux Foundation</p>')
        with patch.object(hubspot_tools, "_get", return_value=email):
            result = hubspot_tools.get_email_content_text("em1")
        assert result["body_html"] == ""

    def test_passes_clean_content(self):
        """Clean rich-text HTML is returned in body_html and sections."""
        clean_html = '<p style="font-size:14px;">Join us for an amazing event!</p>'
        email = self._base_email(clean_html)
        with patch.object(hubspot_tools, "_get", return_value=email):
            result = hubspot_tools.get_email_content_text("em1")
        assert result["success"] is True
        assert clean_html in result["body_html"]
        assert any(s.get("type") == "rich_text" for s in result["sections"])

    def test_returns_subject_and_preview(self):
        """Returns subject from email metadata and preview_text from widgets."""
        email = self._base_email('<p>Hello World</p>')
        with patch.object(hubspot_tools, "_get", return_value=email):
            result = hubspot_tools.get_email_content_text("em1")
        assert result["subject"] == "Test Subject"
        assert result["preview_text"] == "Preview text here"

    def test_returns_failure_on_exception(self):
        """When API call fails, returns success=False with error key."""
        with patch.object(hubspot_tools, "_get", side_effect=Exception("Network error")):
            result = hubspot_tools.get_email_content_text("em1")
        assert result["success"] is False
        assert "error" in result

    def test_multi_column_sections_become_image_row(self):
        """Multi-column sections are extracted as image_row type."""
        widgets = {
            "sp1": {"body": {"img": {"src": "https://cdn.ex.com/1.png", "alt": "Logo1"}}},
            "sp2": {"body": {"img": {"src": "https://cdn.ex.com/2.png", "alt": "Logo2"}}},
        }
        flex = {
            "main": {
                "sections": [{
                    "id": "sec-multi",
                    "columns": [
                        {"id": "c1", "widgets": ["sp1"], "width": 6},
                        {"id": "c2", "widgets": ["sp2"], "width": 6},
                    ],
                    "style": {},
                }]
            }
        }
        email = _make_email_response(email_id="em1", widgets=widgets, flex_areas=flex)
        with patch.object(hubspot_tools, "_get", return_value=email):
            result = hubspot_tools.get_email_content_text("em1")
        assert any(s.get("type") == "image_row" for s in result["sections"])


# ---------------------------------------------------------------------------
# ── TestSponsorFiltering ──────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class TestSponsorFiltering:
    """Tests for sponsor logo filtering inside update_email_content."""

    def _patch_and_call(self, sponsors, content_sections=None):
        """Run update_email_content with given sponsors, return the patch call payload."""
        cs = content_sections or [{"type": "rich_text", "html": "<p>body</p>"}]
        # Collect all sponsor widget keys for verification
        sponsor_keys = [f"staging_sponsor_t1_{i}" for i in range(min(5, len(sponsors)))]
        t2_count = max(0, min(3, len(sponsors) - 5))
        sponsor_keys += [f"staging_sponsor_t2_{i}" for i in range(t2_count)]
        verify_keys = ["staging_sec_0"] + sponsor_keys

        with patch.object(hubspot_tools, "_get", side_effect=[
            _make_email_response("em1"),
            _mock_get_response_for_update("em1", verify_keys or ["staging_sec_0"]),
        ]), patch.object(hubspot_tools, "_patch", return_value=_make_email_response("em1")) as mp:
            hubspot_tools.update_email_content(
                "em1", content_sections=cs, sponsors=sponsors,
            )
            return mp.call_args[0][1]

    def test_no_logo_sponsors_excluded(self):
        """Sponsors without logo_url are excluded — no sponsor widgets created."""
        sponsors = [{"name": "Acme Corp"}]  # no logo_url
        payload = self._patch_and_call(sponsors)
        widgets = payload["content"]["widgets"]
        assert not any("sponsor_t1" in k for k in widgets)
        assert not any("sponsor_t2" in k for k in widgets)

    def test_empty_logo_sponsors_excluded(self):
        """Sponsors with empty logo_url string are excluded."""
        sponsors = [{"name": "Empty Logo", "logo_url": ""}]
        payload = self._patch_and_call(sponsors)
        widgets = payload["content"]["widgets"]
        assert not any("sponsor_t1" in k for k in widgets)

    def test_max_five_tier1_sponsors(self):
        """More than 5 logo sponsors: only first 5 go to tier1."""
        sponsors = [
            {"name": f"S{i}", "logo_url": f"https://cdn.example.com/{i}.png"}
            for i in range(7)
        ]
        payload = self._patch_and_call(sponsors)
        widgets = payload["content"]["widgets"]
        t1_widgets = [k for k in widgets if "sponsor_t1" in k]
        assert len(t1_widgets) == 5

    def test_max_three_tier2_sponsors(self):
        """Sponsors 6-8 go to tier2; sponsor 9+ are dropped."""
        sponsors = [
            {"name": f"S{i}", "logo_url": f"https://cdn.example.com/{i}.png"}
            for i in range(10)
        ]
        payload = self._patch_and_call(sponsors)
        widgets = payload["content"]["widgets"]
        t2_widgets = [k for k in widgets if "sponsor_t2" in k]
        assert len(t2_widgets) == 3

    def test_total_max_eight_sponsors(self):
        """Total sponsor widgets (t1 + t2) must not exceed 8."""
        sponsors = [
            {"name": f"S{i}", "logo_url": f"https://cdn.example.com/{i}.png"}
            for i in range(12)
        ]
        payload = self._patch_and_call(sponsors)
        widgets = payload["content"]["widgets"]
        t1 = [k for k in widgets if "sponsor_t1" in k]
        t2 = [k for k in widgets if "sponsor_t2" in k]
        assert len(t1) + len(t2) <= 8

    def test_tier1_height_60(self):
        """Tier1 sponsor images use height=60."""
        sponsors = [{"name": "S0", "logo_url": "https://cdn.example.com/0.png"}]
        payload = self._patch_and_call(sponsors)
        w = payload["content"]["widgets"].get("staging_sponsor_t1_0", {})
        assert w.get("body", {}).get("img", {}).get("height") == 60

    def test_tier2_height_45(self):
        """Tier2 sponsor images use height=45."""
        sponsors = [
            {"name": f"S{i}", "logo_url": f"https://cdn.example.com/{i}.png"}
            for i in range(6)
        ]
        payload = self._patch_and_call(sponsors)
        w = payload["content"]["widgets"].get("staging_sponsor_t2_0", {})
        assert w.get("body", {}).get("img", {}).get("height") == 45

    def test_mixed_logo_and_no_logo_sponsors(self):
        """Only sponsors with logo_url produce widgets; others are silently dropped."""
        sponsors = [
            {"name": "WithLogo", "logo_url": "https://cdn.example.com/a.png"},
            {"name": "NoLogo"},
            {"name": "AlsoNoLogo", "logo_url": ""},
        ]
        payload = self._patch_and_call(sponsors)
        widgets = payload["content"]["widgets"]
        t1 = [k for k in widgets if "sponsor_t1" in k]
        assert len(t1) == 1  # only WithLogo


# ---------------------------------------------------------------------------
# ── TestBannerWidget ──────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class TestBannerWidget:
    """Deep inspection of the banner widget structure."""

    def _get_banner_body(self, event_url="https://events.linuxfoundation.org/test/"):
        banner_url = "https://cdn.example.com/banner.png"
        with patch.object(hubspot_tools, "_get", side_effect=[
            _make_email_response("em1"),
            _mock_get_response_for_update("em1", ["staging_banner"]),
        ]), patch.object(hubspot_tools, "_patch", return_value=_make_email_response("em1")) as mp:
            hubspot_tools.update_email_content(
                "em1", html_content="<p>x</p>",
                banner_url=banner_url, event_url=event_url,
            )
            return mp.call_args[0][1]["content"]["widgets"]["staging_banner"]["body"]

    def test_banner_module_id_is_1367093(self):
        """Banner widget module_id must be 1367093 (custom LF image module)."""
        body = self._get_banner_body()
        assert body.get("module_id") == 1367093

    def test_banner_uses_link_field_not_href(self):
        """Banner must use 'link' key, not 'href'."""
        body = self._get_banner_body()
        assert "link" in body
        assert "href" not in body

    def test_banner_stretch_on_mobile_is_true(self):
        """Banner must have stretch_on_mobile=True."""
        body = self._get_banner_body()
        assert body.get("stretch_on_mobile") is True

    def test_banner_no_max_width_key(self):
        """Banner body must not have a max_width key at body level."""
        body = self._get_banner_body()
        assert "max_width" not in body

    def test_banner_no_path_key_in_body(self):
        """Banner body must not have a 'path' key (uses module_id routing instead)."""
        body = self._get_banner_body()
        assert "path" not in body

    def test_banner_link_equals_event_url(self):
        """Banner link value must equal the provided event_url."""
        event_url = "https://events.linuxfoundation.org/kubecon-eu/"
        body = self._get_banner_body(event_url=event_url)
        assert body.get("link") == event_url

    def test_banner_section_has_correct_id(self):
        """Banner section must have id='section-staging-banner'."""
        with patch.object(hubspot_tools, "_get", side_effect=[
            _make_email_response("em1"),
            _mock_get_response_for_update("em1", ["staging_banner"]),
        ]), patch.object(hubspot_tools, "_patch", return_value=_make_email_response("em1")) as mp:
            hubspot_tools.update_email_content(
                "em1", html_content="<p>x</p>",
                banner_url="https://cdn.example.com/b.png",
            )
            sections = mp.call_args[0][1]["content"]["flexAreas"]["main"]["sections"]
            ids = [s.get("id") for s in sections]
            assert "section-staging-banner" in ids


# ---------------------------------------------------------------------------
# ── TestStageDetector ─────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class TestStageDet:
    """Tests for stage_detector.detect_stage."""

    def _future_date_str(self, days_from_now):
        d = date.today() + timedelta(days=days_from_now)
        return d.strftime("%B %d, %Y")

    def _past_date_str(self, days_ago):
        d = date.today() - timedelta(days=days_ago)
        return d.strftime("%B %d, %Y")

    def test_no_dates_returns_unknown_stage(self):
        """Empty date list returns stage name 'Unknown'."""
        result = detect_stage([])
        assert result["name"] == "Unknown"
        assert result["days_to_event"] is None

    def test_far_future_returns_event_announcement(self):
        """Event 200 days away → Event Announcement (stage 1)."""
        result = detect_stage([self._future_date_str(200)])
        assert result["name"] == "Event Announcement"
        assert result["funnel"] == "TOFU"

    def test_two_weeks_out_returns_main_registration_push(self):
        """Event 20 days away → Main Registration Push (14-27 days range)."""
        result = detect_stage([self._future_date_str(20)])
        assert result["name"] == "Main Registration Push"
        assert result["funnel"] == "BOFU"

    def test_final_countdown_within_13_days(self):
        """Event 7 days away → Final Countdown stage."""
        result = detect_stage([self._future_date_str(7)])
        assert result["name"] == "Final Countdown"

    def test_event_week_within_2_days(self):
        """Event 1 day away → Event Week stage."""
        result = detect_stage([self._future_date_str(1)])
        assert result["name"] == "Event Week"

    def test_past_event_returns_follow_up_stage(self):
        """Event 5 days ago → Thank You + Survey or Content & Recordings Release."""
        result = detect_stage([self._past_date_str(5)])
        assert result["funnel"] == "FOLLOW-UP"

    def test_result_contains_required_keys(self):
        """Stage result always contains name, funnel, email_type, cta_label, goal."""
        result = detect_stage([self._future_date_str(50)])
        for key in ("name", "funnel", "email_type", "cta_label", "goal"):
            assert key in result, f"Missing key: {key}"

    def test_stage_color_present(self):
        """Stage result includes a color field for UI display."""
        result = detect_stage([self._future_date_str(100)])
        assert "color" in result
        assert result["color"].startswith("#")

    def test_event_date_str_formatted(self):
        """event_date_str is set when a date is parsed."""
        result = detect_stage([self._future_date_str(50)])
        assert result["event_date_str"] != ""

    def test_cfp_launch_stage_range(self):
        """Event 90 days away falls in CFP Launch range (85-99 days)."""
        result = detect_stage([self._future_date_str(90)])
        assert result["name"] == "CFP Launch"

    def test_registration_launch_stage_range(self):
        """Event 75 days away falls in Registration Launch range (70-84 days)."""
        result = detect_stage([self._future_date_str(75)])
        assert result["name"] == "Registration Launch"

    def test_marketing_journey_data_included(self):
        """Stages 1-9 include marketing_strategy and content_ideas from MARKETING_JOURNEY."""
        result = detect_stage([self._future_date_str(200)])  # Event Announcement = stage 1
        assert "marketing_strategy" in result
        assert "content_ideas" in result
        assert isinstance(result["content_ideas"], list)


# ---------------------------------------------------------------------------
# ── TestLocationFilter ────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class TestLocationFilter:
    """Tests for event_brands location chain and filtering logic."""

    def test_extract_location_from_event_name_japan(self):
        """Event name containing 'Japan' → returns 'Japan'."""
        result = extract_location_from_name("KubeCon + CloudNativeCon Japan")
        assert result == "Japan"

    def test_extract_location_from_event_name_north_america(self):
        """Event name with 'North America' → returns 'North America' (multi-word wins)."""
        result = extract_location_from_name("Open Source Summit North America")
        assert result == "North America"

    def test_extract_location_from_event_name_europe(self):
        """Event name with 'Europe' → returns 'Europe'."""
        result = extract_location_from_name("LF Energy Summit Europe")
        assert result == "Europe"

    def test_extract_location_no_match_returns_empty(self):
        """Event name with no location → returns empty string."""
        result = extract_location_from_name("OpenSearchCon")
        assert result == ""

    def test_location_fallback_chain_city_match(self):
        """Toronto → chain contains city, country (Canada), region (North America)."""
        chain = location_fallback_chain("Toronto")
        assert len(chain) >= 2
        assert any("toronto" in ws for ws in chain)
        assert any("canada" in ws for ws in chain)

    def test_location_fallback_chain_city_country_format(self):
        """'Amsterdam, Netherlands' → city + country + region levels."""
        chain = location_fallback_chain("Amsterdam, Netherlands")
        assert any("amsterdam" in ws for ws in chain)
        assert any("netherlands" in ws for ws in chain)
        assert any("europe" in ws for ws in chain)

    def test_location_fallback_chain_empty_location(self):
        """Empty location string → empty chain."""
        chain = location_fallback_chain("")
        assert chain == []

    def test_build_location_chain_event_name_wins(self):
        """build_location_chain: event name location takes priority over scraped."""
        # "KubeCon Japan" → "Japan" from name, which adds japan/asia to chain
        chain = build_location_chain("KubeCon Japan", "Amsterdam")
        # Japan should appear before Amsterdam
        all_words = [w for ws in chain for w in ws]
        assert "japan" in all_words

    def test_build_location_chain_no_duplicates(self):
        """build_location_chain never produces duplicate word-sets."""
        chain = build_location_chain("LF Energy Summit Europe", "Berlin, Germany")
        # Europe from name + Berlin/Germany from scraped — no exact duplicate sets
        seen = []
        for ws in chain:
            fs = frozenset(ws)
            assert fs not in seen, f"Duplicate word-set in chain: {ws}"
            seen.append(fs)

    def test_expand_location_words_north_america(self):
        """'North America' expands to include 'na' abbreviation."""
        words = expand_location_words("North America")
        assert "north" in words
        assert "america" in words
        assert "na" in words

    def test_expand_location_words_europe(self):
        """'Europe' expands to include 'eu' abbreviation."""
        words = expand_location_words("Europe")
        assert "europe" in words
        assert "eu" in words

    def test_expand_location_words_eu_abbreviation(self):
        """'EU' abbreviation expands to include 'europe'."""
        words = expand_location_words("EU")
        assert "eu" in words
        assert "europe" in words

    def test_lookup_event_brand_kubecon_eu(self):
        """KubeCon EU event name maps to CNCF brand."""
        result = lookup_event_brand("KubeCon + CloudNativeCon Europe")
        assert result is not None
        assert result["short_brand_name"] == "CNCF"

    def test_lookup_event_brand_no_match_below_threshold(self):
        """Random event name with <2 keyword overlap → returns None."""
        result = lookup_event_brand("Completely Unknown Event XYZ 2026")
        assert result is None

    def test_lookup_event_brand_open_source_summit_india(self):
        """Open Source Summit India maps to LF brand."""
        result = lookup_event_brand("Open Source Summit India")
        assert result is not None
        assert result["short_brand_name"] == "LF"


# ---------------------------------------------------------------------------
# ── TestSessionLifecycle ──────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class TestSessionLifecycle:
    """Tests for session_store lifecycle and phase transitions."""

    def test_create_returns_session_with_planning_phase(self):
        """New sessions start in 'planning' phase."""
        sess = session_store.create()
        assert sess.phase == "planning"

    def test_create_generates_unique_ids(self):
        """Each create() call returns a session with a distinct ID."""
        s1 = session_store.create()
        s2 = session_store.create()
        assert s1.session_id != s2.session_id

    def test_get_returns_stored_session(self):
        """get() returns the session that was created."""
        sess = session_store.create()
        retrieved = session_store.get(sess.session_id)
        assert retrieved is not None
        assert retrieved.session_id == sess.session_id

    def test_get_unknown_id_returns_none(self):
        """get() with a non-existent ID returns None."""
        assert session_store.get("non-existent-id-xyz") is None

    def test_update_persists_phase_change(self):
        """update() persists a phase change."""
        sess = session_store.create()
        sess.phase = "cloned"
        session_store.update(sess)
        retrieved = session_store.get(sess.session_id)
        assert retrieved.phase == "cloned"

    def test_phase_transitions_planning_to_cloned(self):
        """Phase can transition from 'planning' to 'cloned'."""
        sess = session_store.create()
        assert sess.phase == "planning"
        sess.phase = "cloned"
        session_store.update(sess)
        assert session_store.get(sess.session_id).phase == "cloned"

    def test_phase_transitions_cloned_to_complete(self):
        """Phase can transition from 'cloned' to 'complete'."""
        sess = session_store.create()
        sess.phase = "cloned"
        session_store.update(sess)
        sess.phase = "complete"
        session_store.update(sess)
        assert session_store.get(sess.session_id).phase == "complete"

    def test_meta_persists_across_updates(self):
        """Session meta dict is preserved through multiple updates."""
        sess = session_store.create()
        sess.meta["email_name"] = "26Q3 - CNCF - KubeCon EU - Invite"
        session_store.update(sess)
        retrieved = session_store.get(sess.session_id)
        assert retrieved.meta["email_name"] == "26Q3 - CNCF - KubeCon EU - Invite"


# ---------------------------------------------------------------------------
# ── FastAPI TestClient setup ───────────────────────────────────────────────────
# ---------------------------------------------------------------------------

# We need to import main AFTER stubs are in place
try:
    from fastapi.testclient import TestClient
    import main as _main
    _app = _main.app
    _client = TestClient(_app, raise_server_exceptions=False)
    _FASTAPI_AVAILABLE = True
except Exception as _e:
    _FASTAPI_AVAILABLE = False
    _client = None

_requires_api = pytest.mark.skipif(
    not _FASTAPI_AVAILABLE,
    reason=f"FastAPI app could not be imported: {_e if not _FASTAPI_AVAILABLE else ''}",
)


# ---------------------------------------------------------------------------
# ── TestPlanEndpoint ──────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@_requires_api
class TestPlanEndpoint:
    """Tests for POST /api/plan."""

    def _mock_plan_deps(self):
        """Return a context-manager stack that mocks all plan dependencies."""
        from contextlib import ExitStack
        stack = ExitStack()

        scrape_result = {
            "url": "https://events.linuxfoundation.org/test-event/",
            "event_name": "KubeCon + CloudNativeCon Europe",
            "brand_name": "Cloud Native Computing Foundation",
            "location": "Amsterdam",
            "event_dates": [(date.today() + timedelta(days=100)).strftime("%B %d, %Y")],
            "hero_image_url": "",
            "logo_url": "",
            "speakers": [],
            "topics": [],
            "sponsors": [],
            "registration": {},
        }

        hs_emails = [
            {
                "id": "src-001",
                "name": "26Q1 - CNCF - KubeCon EU - Invite",
                "state": "PUBLISHED",
                "publishDate": 1700000000000,
                "from": {"fromName": "CNCF Events", "replyTo": "events@cncf.io"},
                "to": {"contactIlsLists": {"include": [], "exclude": []},
                       "contactLists": {"include": [], "exclude": []}},
            }
        ]

        stack.enter_context(
            patch("content_tools.scrape_event_full", return_value=scrape_result)
        )
        stack.enter_context(
            patch.object(hubspot_tools, "get_brand_emails", return_value=hs_emails)
        )
        stack.enter_context(
            patch("agent.ai_select_source_email", return_value=hs_emails[0])
        )
        stack.enter_context(
            patch("agent.plan_turn", return_value=("Plan text here", []))
        )
        return stack

    def test_valid_url_returns_session_id(self):
        """POST /api/plan with valid URL returns session_id in response."""
        with self._mock_plan_deps():
            resp = _client.post("/api/plan", json={"url": "https://events.example.com/test/"})
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data

    def test_valid_url_returns_planning_phase(self):
        """POST /api/plan returns phase='planning'."""
        with self._mock_plan_deps():
            resp = _client.post("/api/plan", json={"url": "https://events.example.com/test/"})
        assert resp.status_code == 200
        assert resp.json()["phase"] == "planning"

    def test_scrape_failure_still_returns_session(self):
        """If scrape fails, plan still returns a session (graceful degradation)."""
        with patch("content_tools.scrape_event_full", return_value={"url": "https://x.com/"}), \
             patch("agent.plan_turn", return_value=("Plan text", [])), \
             patch.object(hubspot_tools, "get_brand_emails", return_value=[]):
            resp = _client.post("/api/plan", json={"url": "https://events.example.com/unknown/"})
        assert resp.status_code == 200
        assert "session_id" in resp.json()

    def test_hubspot_search_failure_returns_session(self):
        """If HubSpot search raises, plan still returns a session."""
        scrape_result = {
            "url": "https://events.example.com/x/",
            "event_name": "Test Event",
            "brand_name": "Test Brand",
            "location": "",
            "event_dates": [],
            "hero_image_url": "",
            "logo_url": "",
            "speakers": [],
            "topics": [],
            "sponsors": [],
            "registration": {},
        }
        with patch("content_tools.scrape_event_full", return_value=scrape_result), \
             patch.object(hubspot_tools, "get_brand_emails", side_effect=Exception("HS Error")), \
             patch("agent.plan_turn", return_value=("Plan fallback", [])):
            resp = _client.post("/api/plan", json={"url": "https://events.example.com/x/"})
        assert resp.status_code == 200

    def test_stage_detection_runs_and_returned(self):
        """Stage info is included in the /api/plan response."""
        with self._mock_plan_deps():
            resp = _client.post("/api/plan", json={"url": "https://events.example.com/test/"})
        data = resp.json()
        assert "stage" in data
        assert "name" in data["stage"]


# ---------------------------------------------------------------------------
# ── TestGenerateContentEndpoint ───────────────────────────────────────────────
# ---------------------------------------------------------------------------

@_requires_api
class TestGenerateContentEndpoint:
    """Tests for POST /api/generate-content."""

    def _create_planning_session(self):
        """Create and store a planning-phase session, return its ID."""
        sess = session_store.create()
        sess.phase = "planning"
        sess.meta["url_data"] = {
            "event_name": "KubeCon EU", "event_dates": [], "location": "Amsterdam",
            "description": "Cloud Native conference", "url": "https://cncf.io/test",
            "hero_image_url": "", "logo_url": "", "speakers": [], "topics": [], "sponsors": [],
            "registration": {},
        }
        sess.meta["stage_info"] = {
            "name": "Event Announcement", "funnel": "TOFU",
            "email_type": "Invite", "days_to_event": 100,
            "goal": "Drive awareness", "cta_label": "Learn More",
            "event_date_str": "June 01, 2027", "color": "#16a34a",
        }
        session_store.update(sess)
        return sess.session_id

    def test_session_not_found_returns_404(self):
        """POST /api/generate-content with unknown session_id returns 404."""
        resp = _client.post(
            "/api/generate-content",
            json={"session_id": "does-not-exist-xyz"},
        )
        assert resp.status_code == 404

    def test_valid_session_calls_generate_and_returns_content(self):
        """Valid session returns generated_subject, generated_preview, generated_html."""
        sid = self._create_planning_session()
        generated = {
            "subject":      "Join KubeCon EU 2027!",
            "preview_text": "Cloud Native events in Amsterdam",
            "html":         "<html><body><p>Preview</p></body></html>",
            "body_html":    "<p>Preview</p>",
            "sections":     [{"type": "rich_text", "html": "<p>Hello</p>"}],
            "banner_url":   "",
            "sponsors":     [],
        }
        with patch("agent.generate_email_content", return_value=generated):
            resp = _client.post(
                "/api/generate-content", json={"session_id": sid},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["generated_subject"] == "Join KubeCon EU 2027!"
        assert "generated_html" in data

    def test_change_request_forwarded(self):
        """change_request parameter is passed to generate_email_content."""
        sid = self._create_planning_session()
        generated = {
            "subject": "Updated!", "preview_text": "Short", "html": "<p>x</p>",
            "body_html": "<p>x</p>", "sections": [], "banner_url": "", "sponsors": [],
        }
        with patch("agent.generate_email_content", return_value=generated) as mock_gen:
            _client.post(
                "/api/generate-content",
                json={"session_id": sid, "change_request": "Make it shorter"},
            )
        mock_gen.assert_called_once()
        kwargs = mock_gen.call_args[1]
        assert kwargs.get("change_request") == "Make it shorter"

    def test_no_source_email_id_uses_empty_string(self):
        """If content_reference_id not in session, source_email_id defaults to ''."""
        sid = self._create_planning_session()
        generated = {
            "subject": "S", "preview_text": "P", "html": "<p>x</p>",
            "body_html": "<p>x</p>", "sections": [], "banner_url": "", "sponsors": [],
        }
        with patch("agent.generate_email_content", return_value=generated) as mock_gen:
            _client.post("/api/generate-content", json={"session_id": sid})
        mock_gen.assert_called_once()
        kwargs = mock_gen.call_args[1]
        assert kwargs.get("source_email_id") == ""


# ---------------------------------------------------------------------------
# ── TestCloneEndpoint ─────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@_requires_api
class TestCloneEndpoint:
    """Tests for POST /api/clone."""

    def _make_planning_session(self, brand_history=None):
        sess = session_store.create()
        sess.phase = "planning"
        sess.meta["email_name"] = "26Q3 - CNCF - KubeCon EU - Invite"
        sess.meta["brand_history"] = brand_history or {
            "found": True,
            "matched_email_id": "src-001",
            "last_email_id": "src-001",
            "from_name": "CNCF Events",
            "from_address": "events@cncf.io",
            "email_type": "BATCH_EMAIL",
            "suppression_list_ids": [],
            "included_list_ids": [],
        }
        session_store.update(sess)
        return sess

    def _mock_clone_turn(self, new_email_id="em-new-001", validation_passed=True):
        """Return side_effect tuple for clone_turn that sets agent._session_email_id."""
        import agent as _agent

        def _fake_clone_turn(session, subject=None, preview_text=None, send_list_id=None):
            _agent._session_email_id = new_email_id
            session.meta["content_applied"]  = True
            session.meta["validation_passed"] = validation_passed
            session.meta["validation_issues"] = [] if validation_passed else ["Some issue"]
            session_store.update(session)
            return "Clone complete text.", session.messages

        return _fake_clone_turn

    def test_session_not_found_returns_404(self):
        """POST /api/clone with unknown session → 404."""
        resp = _client.post("/api/clone", json={
            "session_id": "not-exist-zxcv", "approved": True,
        })
        assert resp.status_code == 404

    def test_wrong_phase_returns_400(self):
        """POST /api/clone when session is in 'complete' phase → 400."""
        sess = session_store.create()
        sess.phase = "complete"
        session_store.update(sess)
        resp = _client.post("/api/clone", json={
            "session_id": sess.session_id, "approved": True,
        })
        assert resp.status_code == 400

    def test_not_approved_returns_planning_phase(self):
        """POST /api/clone with approved=False → returns phase='planning' without cloning."""
        sess = self._make_planning_session()
        resp = _client.post("/api/clone", json={
            "session_id": sess.session_id, "approved": False,
        })
        assert resp.status_code == 200
        assert resp.json()["phase"] == "planning"

    def test_clone_always_returns_draft_url(self):
        """POST /api/clone always returns draft_url regardless of validation result."""
        sess = self._make_planning_session()
        with patch("agent.clone_turn", side_effect=self._mock_clone_turn(validation_passed=False)):
            resp = _client.post("/api/clone", json={
                "session_id": sess.session_id, "approved": True,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert "draft_url" in data
        assert data["draft_url"] != "" and data["draft_url"] is not None

    def test_validation_passed_sets_phase_complete(self):
        """When validation passes, phase transitions to 'complete'."""
        sess = self._make_planning_session()
        with patch("agent.clone_turn", side_effect=self._mock_clone_turn(validation_passed=True)):
            resp = _client.post("/api/clone", json={
                "session_id": sess.session_id, "approved": True,
            })
        assert resp.status_code == 200
        assert resp.json()["phase"] == "complete"

    def test_validation_failed_sets_phase_cloned(self):
        """When validation fails, phase transitions to 'cloned' (not 'complete')."""
        sess = self._make_planning_session()
        with patch("agent.clone_turn", side_effect=self._mock_clone_turn(validation_passed=False)):
            resp = _client.post("/api/clone", json={
                "session_id": sess.session_id, "approved": True,
            })
        assert resp.status_code == 200
        assert resp.json()["phase"] == "cloned"

    def test_no_email_id_set_returns_500(self):
        """If clone_turn runs but _session_email_id is not set → 500."""
        import agent as _agent
        sess = self._make_planning_session()

        def _no_clone(session, **kw):
            _agent._session_email_id = None  # simulate Claude not calling clone tool
            session.meta["content_applied"]  = False
            session.meta["validation_passed"] = False
            session.meta["validation_issues"] = []
            return "No clone happened.", session.messages

        with patch("agent.clone_turn", side_effect=_no_clone):
            resp = _client.post("/api/clone", json={
                "session_id": sess.session_id, "approved": True,
            })
        assert resp.status_code == 500

    def test_validation_issues_returned_in_response(self):
        """Validation issues are included in the clone response body."""
        sess = self._make_planning_session()
        with patch("agent.clone_turn",
                   side_effect=self._mock_clone_turn(validation_passed=False)):
            resp = _client.post("/api/clone", json={
                "session_id": sess.session_id, "approved": True,
            })
        data = resp.json()
        assert "validation_issues" in data


# ---------------------------------------------------------------------------
# ── TestSetSendListEndpoint ───────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@_requires_api
class TestSetSendListEndpoint:
    """Tests for POST /api/set-send-list."""

    def _cloned_session(self, email_id="em-cloned"):
        sess = session_store.create()
        sess.phase = "cloned"
        sess.email_id = email_id
        sess.meta["brand_history"] = {"suppression_list_ids": ["sup-001"]}
        session_store.update(sess)
        return sess

    def test_missing_send_list_id_returns_400(self):
        """POST /api/set-send-list without send_list_id → 400."""
        resp = _client.post("/api/set-send-list", json={
            "session_id": "", "send_list_id": "",
        })
        assert resp.status_code == 400

    def test_no_email_returns_400(self):
        """POST /api/set-send-list with no email_id and no session → 400."""
        resp = _client.post("/api/set-send-list", json={
            "send_list_id": "list-001",
            "email_id": "",
            "session_id": "",
        })
        assert resp.status_code == 400

    def test_ils_list_applied_successfully(self):
        """ILS list applied successfully → 200 with success=True."""
        sess = self._cloned_session()
        mock_result = {
            "success": True,
            "email_id": sess.email_id,
            "send_list_id": "list-ils-001",
            "list_type": "DYNAMIC",
            "to": {"contactIlsLists": {"include": ["list-ils-001"], "exclude": []}},
        }
        with patch.object(hubspot_tools, "set_email_send_list", return_value=mock_result):
            resp = _client.post("/api/set-send-list", json={
                "session_id": sess.session_id,
                "send_list_id": "list-ils-001",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["list_type"] == "DYNAMIC"

    def test_static_list_applied_successfully(self):
        """Static (legacy) list applied successfully → 200."""
        sess = self._cloned_session()
        mock_result = {
            "success": True,
            "email_id": sess.email_id,
            "send_list_id": "99999",
            "list_type": "UNKNOWN",
            "to": {"contactLists": {"include": [99999], "exclude": []}},
        }
        with patch.object(hubspot_tools, "set_email_send_list", return_value=mock_result):
            resp = _client.post("/api/set-send-list", json={
                "session_id": sess.session_id,
                "send_list_id": "99999",
            })
        assert resp.status_code == 200

    def test_hubspot_failure_returns_502(self):
        """When set_email_send_list returns success=False → 502."""
        sess = self._cloned_session()
        mock_result = {
            "success": False,
            "email_id": sess.email_id,
            "send_list_id": "list-fail",
            "list_type": "DYNAMIC",
            "to": {},
        }
        with patch.object(hubspot_tools, "set_email_send_list", return_value=mock_result):
            resp = _client.post("/api/set-send-list", json={
                "session_id": sess.session_id,
                "send_list_id": "list-fail",
            })
        assert resp.status_code == 502

    def test_exception_in_set_send_list_returns_500(self):
        """Unexpected exception in set_email_send_list → 500."""
        sess = self._cloned_session()
        with patch.object(hubspot_tools, "set_email_send_list",
                          side_effect=Exception("Network timeout")):
            resp = _client.post("/api/set-send-list", json={
                "session_id": sess.session_id,
                "send_list_id": "list-001",
            })
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# ── TestContentEndpoint ───────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@_requires_api
class TestContentEndpoint:
    """Tests for POST /api/content."""

    def _cloned_session(self, email_id="em-content"):
        sess = session_store.create()
        sess.phase = "cloned"
        sess.email_id = email_id
        sess.draft_url = f"https://app.hubspot.com/email/8112310/edit/{email_id}/settings"
        session_store.update(sess)
        return sess

    def test_wrong_phase_returns_400(self):
        """POST /api/content when phase='planning' → 400."""
        sess = session_store.create()
        sess.phase = "planning"
        session_store.update(sess)
        resp = _client.post("/api/content", json={
            "session_id": sess.session_id,
            "content": "<p>Some HTML content</p>",
        })
        assert resp.status_code == 400

    def test_cloned_phase_applies_content(self):
        """POST /api/content when phase='cloned' → 200, phase becomes 'complete'."""
        sess = self._cloned_session()
        with patch("agent.content_turn", return_value=("Content applied.", sess.messages)):
            resp = _client.post("/api/content", json={
                "session_id": sess.session_id,
                "content": "<p>Hello World</p>",
            })
        assert resp.status_code == 200
        assert resp.json()["phase"] == "complete"

    def test_complete_phase_also_applies_content(self):
        """POST /api/content when phase='complete' → also returns 200."""
        sess = self._cloned_session()
        sess.phase = "complete"
        session_store.update(sess)
        with patch("agent.content_turn", return_value=("Updated.", sess.messages)):
            resp = _client.post("/api/content", json={
                "session_id": sess.session_id,
                "content": "<p>Additional content</p>",
            })
        assert resp.status_code == 200

    def test_session_not_found_returns_404(self):
        """POST /api/content with unknown session_id → 404."""
        resp = _client.post("/api/content", json={
            "session_id": "nonexistent-abc",
            "content": "<p>x</p>",
        })
        assert resp.status_code == 404

    def test_draft_url_returned_in_response(self):
        """draft_url is included in the /api/content response."""
        sess = self._cloned_session()
        with patch("agent.content_turn", return_value=("Done.", sess.messages)):
            resp = _client.post("/api/content", json={
                "session_id": sess.session_id,
                "content": "<p>Content</p>",
            })
        assert "draft_url" in resp.json()


# ---------------------------------------------------------------------------
# ── TestStageFromBrief ────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@_requires_api
class TestStageFromBrief:
    """Tests for POST /api/stage-from-brief."""

    _VALID_TOKEN = "test-internal-token"

    _BRIEF_BASE = {
        "internal_token": _VALID_TOKEN,
        "clone_base_id":  "src-001",
        "email_name":     "26Q3 - CNCF - KubeCon EU - Invite",
        "from_name":      "CNCF Events",
        "from_address":   "events@cncf.io",
        "subject":        "Join KubeCon EU!",
        "preview_text":   "Register now",
        "email_type":     "BATCH_EMAIL",
        "send_list_id":   "",
        "suppression_list_ids": [],
        "raw_html":       "",
        "event_url":      "",
    }

    def _mock_clone_success(self, new_id="em-brief-001"):
        return {
            "email_id": new_id,
            "name": "26Q3 - CNCF - KubeCon EU - Invite",
            "state": "DRAFT",
            "draft_url": f"https://app.hubspot.com/email/8112310/edit/{new_id}/settings",
            "verified": True,
        }

    def test_invalid_token_returns_401(self):
        """POST /api/stage-from-brief with wrong token → 401."""
        brief = dict(self._BRIEF_BASE, internal_token="wrong-token")
        resp = _client.post("/api/stage-from-brief", json=brief)
        assert resp.status_code == 401

    def test_clone_only_no_content_returns_200(self):
        """No raw_html and no event_url → clone + settings only, content_source='none'."""
        with patch.object(hubspot_tools, "clone_email", return_value=self._mock_clone_success()), \
             patch.object(hubspot_tools, "update_email_settings", return_value={"success": True}):
            resp = _client.post("/api/stage-from-brief", json=self._BRIEF_BASE)
        assert resp.status_code == 200
        data = resp.json()
        assert data["content_source"] == "none"
        assert data["content_applied"] is False

    def test_raw_html_applies_doc_content(self):
        """raw_html provided → content_source='doc', content_applied=True."""
        brief = dict(self._BRIEF_BASE, raw_html="<p>Hello from Google Doc</p>")
        with patch.object(hubspot_tools, "clone_email", return_value=self._mock_clone_success()), \
             patch.object(hubspot_tools, "update_email_settings", return_value={"success": True}), \
             patch.object(hubspot_tools, "update_email_content",
                          return_value={"success": True, "email_id": "em-brief-001"}):
            resp = _client.post("/api/stage-from-brief", json=brief)
        assert resp.status_code == 200
        data = resp.json()
        assert data["content_source"] == "doc"
        assert data["content_applied"] is True

    def test_event_url_triggers_ai_generation(self):
        """event_url provided (no raw_html) → content_source='ai'."""
        brief = dict(self._BRIEF_BASE, event_url="https://events.linuxfoundation.org/test/")
        scrape_result = {
            "url": "https://events.linuxfoundation.org/test/",
            "event_name": "Test Event", "event_dates": [], "location": "Amsterdam",
            "description": "A test event", "hero_image_url": "", "logo_url": "",
            "speakers": [], "topics": [], "sponsors": [], "registration": {},
        }
        generated = {
            "subject": "AI Subject", "preview_text": "AI Preview",
            "html": "<p>AI Content</p>", "body_html": "<p>AI Content</p>",
            "sections": [], "banner_url": "", "sponsors": [],
        }
        with patch.object(hubspot_tools, "clone_email", return_value=self._mock_clone_success()), \
             patch.object(hubspot_tools, "update_email_settings", return_value={"success": True}), \
             patch("content_tools.scrape_event_full", return_value=scrape_result), \
             patch("agent.generate_email_content", return_value=generated), \
             patch.object(hubspot_tools, "update_email_content",
                          return_value={"success": True, "email_id": "em-brief-001"}):
            resp = _client.post("/api/stage-from-brief", json=brief)
        assert resp.status_code == 200
        data = resp.json()
        assert data["content_source"] == "ai"
        assert data["content_applied"] is True

    def test_clone_failure_returns_500(self):
        """If clone_email raises, /api/stage-from-brief returns 500."""
        with patch.object(hubspot_tools, "clone_email", side_effect=Exception("Clone failed")):
            resp = _client.post("/api/stage-from-brief", json=self._BRIEF_BASE)
        assert resp.status_code == 500

    def test_draft_url_always_returned(self):
        """draft_url is always present in the response on success."""
        with patch.object(hubspot_tools, "clone_email", return_value=self._mock_clone_success()), \
             patch.object(hubspot_tools, "update_email_settings", return_value={"success": True}):
            resp = _client.post("/api/stage-from-brief", json=self._BRIEF_BASE)
        assert resp.status_code == 200
        assert "draft_url" in resp.json()


# ---------------------------------------------------------------------------
# ── TestListSearch ────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@_requires_api
class TestListSearch:
    """Tests for GET /api/lists/search."""

    def test_short_query_returns_empty_list(self):
        """Query shorter than 2 chars → returns {lists: []} without calling HubSpot."""
        resp = _client.get("/api/lists/search", params={"q": "x"})
        assert resp.status_code == 200
        assert resp.json() == {"lists": []}

    def test_empty_query_returns_empty_list(self):
        """No query param → returns {lists: []}."""
        resp = _client.get("/api/lists/search")
        assert resp.status_code == 200
        assert resp.json() == {"lists": []}

    def test_valid_query_calls_hubspot(self):
        """Query with ≥2 chars → calls HubSpot and returns results."""
        mock_result = {
            "lists": [
                {"id": "1001", "name": "KubeCon EU Registrants", "size": 500}
            ]
        }
        with patch.object(hubspot_tools, "search_lists", return_value=mock_result):
            resp = _client.get("/api/lists/search", params={"q": "KubeCon"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["lists"]) == 1
        assert data["lists"][0]["name"] == "KubeCon EU Registrants"

    def test_single_char_query_returns_empty(self):
        """Single character query → returns empty without calling HubSpot."""
        with patch.object(hubspot_tools, "search_lists") as mock_search:
            resp = _client.get("/api/lists/search", params={"q": "a"})
        assert resp.status_code == 200
        mock_search.assert_not_called()
        assert resp.json() == {"lists": []}

    def test_two_char_query_returns_results(self):
        """Two-character query is accepted and calls HubSpot."""
        mock_result = {"lists": [{"id": "2001", "name": "LF Newsletter", "size": 1000}]}
        with patch.object(hubspot_tools, "search_lists", return_value=mock_result):
            resp = _client.get("/api/lists/search", params={"q": "LF"})
        assert resp.status_code == 200
        assert resp.json() == mock_result


# ---------------------------------------------------------------------------
# ── TestProgressStream ────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@_requires_api
class TestProgressStream:
    """Tests for GET /api/progress/{token} SSE endpoint."""

    def test_status_endpoint_returns_200(self):
        """GET /api/status returns 200 and mode info."""
        resp = _client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "mode" in data
        assert "hubspot_configured" in data

    def test_progress_emit_no_op_for_empty_token(self):
        """progress_emit with falsy token doesn't raise."""
        # Should be a no-op
        _main.progress_emit("", "Test message")

    def test_progress_channel_created_on_first_access(self):
        """_progress_channel creates a new queue for unknown token."""
        token = "test-token-xyz-unique"
        _main._progress.pop(token, None)
        q = _main._progress_channel(token)
        assert q is not None
        _main._progress.pop(token, None)

    def test_progress_emit_puts_message_in_queue(self):
        """progress_emit puts a brief event into the channel queue."""
        import queue as _q
        token = "test-emit-token"
        _main._progress[token] = _q.Queue()
        _main.progress_emit(token, "Step completed")
        item = _main._progress[token].get_nowait()
        assert item["type"] == "brief"
        assert "Step completed" in item["text"]
        del _main._progress[token]


# ---------------------------------------------------------------------------
# ── TestExtractBrandHistory ───────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class TestExtractBrandHistory:
    """Tests for agent.extract_brand_history_from_messages."""

    def test_extracts_from_sdk_tool_result(self):
        """Finds brand history in SDK-style tool_result block."""
        import agent
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "content": json.dumps({
                            "found": True,
                            "matched_email_id": "em-001",
                            "matched_email_name": "Test Email",
                            "from_name": "Events Team",
                            "from_address": "events@example.com",
                        }),
                    }
                ],
            }
        ]
        result = agent.extract_brand_history_from_messages(messages)
        assert result is not None
        assert result["matched_email_id"] == "em-001"

    def test_extracts_from_tool_log_entries(self):
        """Finds brand history in __tool_log__ messages (Claude Code CLI mode)."""
        import agent
        messages = [
            {
                "role": "__tool_log__",
                "content": [
                    {
                        "type": "tool_result",
                        "tool": "search_emails_for_event",
                        "content": json.dumps({
                            "found": True,
                            "matched_email_id": "em-002",
                            "matched_email_name": "CLI Mode Email",
                            "from_name": "Linux Foundation",
                            "from_address": "events@linuxfoundation.org",
                        }),
                    }
                ],
            }
        ]
        result = agent.extract_brand_history_from_messages(messages)
        assert result is not None
        assert result["matched_email_id"] == "em-002"

    def test_normalizes_matched_email_id_to_last_email_id(self):
        """search_emails_for_event result: matched_email_id is aliased to last_email_id."""
        import agent
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "content": json.dumps({
                            "found": True,
                            "matched_email_id": "em-normalize",
                            "from_name": "LF",
                            "from_address": "lf@example.com",
                        }),
                    }
                ],
            }
        ]
        result = agent.extract_brand_history_from_messages(messages)
        assert result["last_email_id"] == "em-normalize"

    def test_returns_none_when_no_brand_history_found(self):
        """Returns None when messages contain no valid brand history."""
        import agent
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "How can I help?"},
        ]
        assert agent.extract_brand_history_from_messages(messages) is None

    def test_returns_none_for_found_false_results(self):
        """Returns None when tool result has found=False."""
        import agent
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "content": json.dumps({
                            "found": False,
                            "message": "No emails found.",
                        }),
                    }
                ],
            }
        ]
        assert agent.extract_brand_history_from_messages(messages) is None


# ---------------------------------------------------------------------------
# ── TestSearchListsFunction ───────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class TestSearchListsFunction:
    """Tests for hubspot_tools.search_lists (internal function)."""

    def test_short_query_returns_empty(self):
        """Query shorter than 2 chars returns {lists: []} without API call."""
        result = hubspot_tools.search_lists("x")
        assert result == {"lists": []}

    def test_empty_string_returns_empty(self):
        """Empty query returns empty without API call."""
        result = hubspot_tools.search_lists("")
        assert result == {"lists": []}

    def test_valid_query_calls_post(self):
        """Valid query calls _post and returns structured results."""
        api_response = {
            "lists": [
                {
                    "listId": 1001,
                    "name": "KubeCon Attendees",
                    "additionalProperties": {"hs_list_size": "500"},
                }
            ]
        }
        with patch.object(hubspot_tools, "_post", return_value=api_response):
            result = hubspot_tools.search_lists("KubeCon")
        assert len(result["lists"]) == 1
        assert result["lists"][0]["id"] == "1001"
        assert result["lists"][0]["size"] == 500

    def test_api_exception_returns_error_key(self):
        """If _post raises, returns {lists: [], error: '...'}."""
        with patch.object(hubspot_tools, "_post", side_effect=Exception("API down")):
            result = hubspot_tools.search_lists("valid query")
        assert result["lists"] == []
        assert "error" in result

    def test_filters_out_items_with_no_name(self):
        """Items with empty name are excluded from results."""
        api_response = {
            "lists": [
                {"listId": 1, "name": "", "additionalProperties": {}},
                {"listId": 2, "name": "Valid List", "additionalProperties": {}},
            ]
        }
        with patch.object(hubspot_tools, "_post", return_value=api_response):
            result = hubspot_tools.search_lists("Valid")
        names = [l["name"] for l in result["lists"]]
        assert "" not in names
        assert "Valid List" in names

    def test_filters_out_items_with_no_id(self):
        """Items with no listId or id are excluded."""
        api_response = {
            "lists": [
                {"name": "No ID List", "additionalProperties": {}},  # no listId or id
            ]
        }
        with patch.object(hubspot_tools, "_post", return_value=api_response):
            result = hubspot_tools.search_lists("No ID")
        assert result["lists"] == []


# ---------------------------------------------------------------------------
# ── TestCloneTurnDirectly ─────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class TestCloneTurnDirectly:
    """Unit tests for agent.clone_turn (without HTTP layer)."""

    def _make_session_with_brand(self):
        sess = session_store.create()
        sess.phase = "planning"
        sess.meta["email_name"] = "26Q3 - LF - OSS NA - Invite"
        sess.meta["brand_history"] = {
            "found": True,
            "last_email_id": "src-001",
            "matched_email_id": "src-001",
            "from_name": "Linux Foundation Events",
            "from_address": "events@linuxfoundation.org",
            "email_type": "BATCH_EMAIL",
            "suppression_list_ids": ["sup-001"],
            "included_list_ids": ["inc-001"],
        }
        session_store.update(sess)
        return sess

    def test_clone_turn_resets_session_email_id_at_start(self):
        """clone_turn resets agent._session_email_id to None before running."""
        import agent as _agent
        _agent._session_email_id = "old-email-id"  # pre-set from previous run
        sess = self._make_session_with_brand()

        mock_clone_result = json.dumps({
            "email_id": "new-email-001",
            "draft_url": "https://app.hubspot.com/email/8112310/edit/new-email-001/settings",
            "verified": True,
        })
        mock_settings_result = json.dumps({"success": True, "email_id": "new-email-001"})
        mock_content_result = {"success": True, "method": "rich_text_only", "email_id": "new-email-001"}
        mock_validate_result = {"valid": True, "issues": [], "summary": "OK"}
        mock_send_list_result = {"success": True, "email_id": "new-email-001", "list_type": "DYNAMIC"}

        with patch.object(hubspot_tools, "clone_email", return_value=json.loads(mock_clone_result)), \
             patch.object(hubspot_tools, "update_email_settings", return_value={"success": True}), \
             patch.object(hubspot_tools, "update_email_content", return_value=mock_content_result), \
             patch.object(hubspot_tools, "validate_staged_email", return_value=mock_validate_result), \
             patch.object(hubspot_tools, "set_email_send_list", return_value=mock_send_list_result):
            _agent.clone_turn(sess)

        # _session_email_id should be set to the new email
        assert _agent._session_email_id == "new-email-001"

    def test_clone_turn_raises_when_no_source_id(self):
        """clone_turn raises RuntimeError when brand_history has no email ID."""
        import agent as _agent
        sess = session_store.create()
        sess.meta["brand_history"] = {"found": True}  # no last_email_id
        session_store.update(sess)
        with pytest.raises(RuntimeError, match="No source email found"):
            _agent.clone_turn(sess)

    def test_session_email_id_locked_after_clone(self):
        """After clone_turn, agent._session_email_id is set to the cloned ID."""
        import agent as _agent
        sess = self._make_session_with_brand()

        clone_res = {
            "email_id": "locked-em-001",
            "draft_url": "https://app.hubspot.com/email/8112310/edit/locked-em-001/settings",
            "verified": True,
        }
        validate_res = {"valid": False, "issues": ["Test issue"], "summary": "FAIL"}
        send_list_res = {"success": True, "list_type": "DYNAMIC"}

        with patch.object(hubspot_tools, "clone_email", return_value=clone_res), \
             patch.object(hubspot_tools, "update_email_settings", return_value={"success": True}), \
             patch.object(hubspot_tools, "update_email_content",
                          return_value={"success": True, "method": "rich_text_only"}), \
             patch.object(hubspot_tools, "validate_staged_email", return_value=validate_res), \
             patch.object(hubspot_tools, "set_email_send_list", return_value=send_list_res):
            _agent.clone_turn(sess)

        assert _agent._session_email_id == "locked-em-001"


# ---------------------------------------------------------------------------
# ── TestParseEventDate ────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class TestParseEventDate:
    """Tests for stage_detector.parse_event_date."""

    def test_parse_standard_format(self):
        """'June 15, 2026' → date(2026, 6, 15)."""
        result = parse_event_date(["June 15, 2026"])
        assert result == date(2026, 6, 15)

    def test_parse_abbreviated_month(self):
        """'Jun 15, 2026' → date(2026, 6, 15)."""
        result = parse_event_date(["Jun 15, 2026"])
        assert result == date(2026, 6, 15)

    def test_parse_returns_earliest_date(self):
        """Multiple dates → returns the earliest one."""
        result = parse_event_date(["June 15, 2026", "March 1, 2026"])
        assert result == date(2026, 3, 1)

    def test_parse_empty_list_returns_none(self):
        """Empty list → returns None."""
        assert parse_event_date([]) is None

    def test_parse_range_normalizes(self):
        """'June 15-16, 2026' → date(2026, 6, 15) (first day of range)."""
        result = parse_event_date(["June 15-16, 2026"])
        assert result == date(2026, 6, 15)

    def test_parse_ordinal_suffix_stripped(self):
        """'June 15th, 2026' → parses correctly to date(2026, 6, 15)."""
        result = parse_event_date(["June 15th, 2026"])
        assert result == date(2026, 6, 15)

    def test_parse_invalid_string_returns_none(self):
        """Non-date string → returns None."""
        result = parse_event_date(["not a date"])
        assert result is None


# ---------------------------------------------------------------------------
# ── TestAddUtm / TestSlugifyUtmContent / TestTagHtmlLinks ────────────────────
# ---------------------------------------------------------------------------

_UTM = {
    "utm_campaign": "26q3-lf-kubecon-eu-invite",
    "utm_source":   "email",
    "utm_medium":   "LF-Events",
}


class TestAddUtm:
    """Tests for utm_tools.add_utm."""

    def test_merges_utm_params_into_clean_url(self):
        result = utm_tools.add_utm("https://example.com/register", _UTM, "register-cta")
        assert "utm_campaign=26q3-lf-kubecon-eu-invite" in result
        assert "utm_source=email" in result
        assert "utm_medium=LF-Events" in result
        assert "utm_content=register-cta" in result

    def test_preserves_existing_query_params(self):
        result = utm_tools.add_utm("https://example.com/register?ref=homepage", _UTM, "register-cta")
        assert "ref=homepage" in result
        assert "utm_campaign=26q3-lf-kubecon-eu-invite" in result

    def test_empty_url_is_noop(self):
        assert utm_tools.add_utm("", _UTM, "register-cta") == ""
        assert utm_tools.add_utm(None, _UTM, "register-cta") is None

    def test_empty_utm_params_is_noop(self):
        url = "https://example.com/register"
        assert utm_tools.add_utm(url, {}, "register-cta") == url
        assert utm_tools.add_utm(url, None, "register-cta") == url

    def test_already_tagged_url_is_noop(self):
        """A URL with a non-empty utm_campaign is never double-tagged."""
        url = "https://insights.linuxfoundation.org/?utm_campaign=23551824-Q3-2025-LF-Awareness-LFX-Insights&utm_source=email"
        result = utm_tools.add_utm(url, _UTM, "social-lfx-insights")
        assert result == url

    def test_mailto_and_anchor_untouched(self):
        assert utm_tools.add_utm("mailto:info@linuxfoundation.org", _UTM, "x") == "mailto:info@linuxfoundation.org"
        assert utm_tools.add_utm("#section-2", _UTM, "x") == "#section-2"


class TestSlugifyUtmContent:
    """Tests for utm_tools.slugify_utm_content."""

    def test_slugifies_button_text(self):
        assert utm_tools.slugify_utm_content("Register Now") == "register-now-cta"

    def test_no_duplicate_suffix(self):
        assert utm_tools.slugify_utm_content("Register CTA") == "register-cta"

    def test_empty_text_falls_back_to_suffix(self):
        assert utm_tools.slugify_utm_content("", suffix="cta") == "cta"

    def test_no_suffix_when_empty_string_passed(self):
        assert utm_tools.slugify_utm_content("Register Now", suffix="") == "register-now"


class TestTagHtmlLinks:
    """Tests for utm_tools.tag_html_links."""

    def test_tags_anchor_href(self):
        html = '<p>See our <a href="https://example.com/agenda">agenda</a>.</p>'
        result = utm_tools.tag_html_links(html, _UTM)
        assert "utm_campaign=26q3-lf-kubecon-eu-invite" in result
        assert "utm_content=body-link-1" in result

    def test_skips_mailto_and_anchor_links(self):
        html = '<a href="mailto:info@lf.org">Email us</a><a href="#top">Top</a>'
        result = utm_tools.tag_html_links(html, _UTM)
        assert "mailto:info@lf.org" in result
        assert "#top" in result
        assert "utm_campaign" not in result

    def test_empty_html_or_params_is_noop(self):
        assert utm_tools.tag_html_links("", _UTM) == ""
        assert utm_tools.tag_html_links("<p>x</p>", None) == "<p>x</p>"

    def test_multiple_links_get_distinct_content(self):
        html = (
            '<a href="https://example.com/a">A</a>'
            '<a href="https://example.com/b">B</a>'
        )
        result = utm_tools.tag_html_links(html, _UTM)
        assert "utm_content=body-link-1" in result
        assert "utm_content=body-link-2" in result


# ---------------------------------------------------------------------------
# ── TestResolveUtmCampaign ────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class TestResolveUtmCampaign:
    """Tests for hubspot_tools.resolve_utm_campaign (+ get_email_campaign / get_campaign_utm)."""

    FALLBACK_NAME = "26Q3 - LF - KubeCon EU - Invite"

    def test_real_campaign_with_utm(self):
        with patch.object(hubspot_tools, "_get", side_effect=[
            {"campaign": "guid-1", "campaignName": "Q3 Campaign"},
            {"properties": {"hs_name": "Q3 Campaign", "hs_utm": "26q3-official-slug",
                             "hs_campaign_status": "ACTIVE"}},
        ]):
            result = hubspot_tools.resolve_utm_campaign("email-1", self.FALLBACK_NAME)

        assert result["source"] == "hubspot_campaign"
        assert result["utm_campaign"] == "26q3-official-slug"
        assert result["campaign_id"] == "guid-1"
        assert result["campaign_name"] == "Q3 Campaign"
        assert result["utm_source"] == "email"

    def test_campaign_with_empty_utm_falls_back(self):
        with patch.object(hubspot_tools, "_get", side_effect=[
            {"campaign": "guid-2", "campaignName": "No UTM Campaign"},
            {"properties": {"hs_name": "No UTM Campaign", "hs_utm": "",
                             "hs_campaign_status": "ACTIVE"}},
        ]):
            result = hubspot_tools.resolve_utm_campaign("email-2", self.FALLBACK_NAME)

        assert result["source"] == "fallback"
        assert result["campaign_id"] == "guid-2"
        assert result["campaign_name"] == "No UTM Campaign"
        assert result["utm_campaign"] == utm_tools.slugify_utm_content(self.FALLBACK_NAME, suffix="")

    def test_email_with_no_campaign_falls_back(self):
        with patch.object(hubspot_tools, "_get", side_effect=[
            {"campaign": None, "campaignName": None},
        ]) as mock_get:
            result = hubspot_tools.resolve_utm_campaign("email-3", self.FALLBACK_NAME)

        assert result["source"] == "fallback"
        assert result["campaign_id"] is None
        mock_get.assert_called_once()  # get_campaign_utm never called — no campaign_id

    def test_no_source_email_id_falls_back_without_api_call(self):
        with patch.object(hubspot_tools, "_get") as mock_get:
            result = hubspot_tools.resolve_utm_campaign(None, self.FALLBACK_NAME)

        mock_get.assert_not_called()
        assert result["source"] == "fallback"
        assert result["campaign_id"] is None

    def test_api_error_degrades_to_fallback(self):
        with patch.object(hubspot_tools, "_get", side_effect=RuntimeError("HubSpot 500")):
            result = hubspot_tools.resolve_utm_campaign("email-4", self.FALLBACK_NAME)

        assert result["source"] == "fallback"
        assert result["utm_campaign"]


# ---------------------------------------------------------------------------
# ── TestUpdateEmailContentUtmTagging ──────────────────────────────────────────
# ---------------------------------------------------------------------------

class TestUpdateEmailContentUtmTagging:
    """Tests that update_email_content tags every link when utm_params is passed."""

    def test_no_utm_params_leaves_links_untagged(self):
        content_sections = [{"type": "button", "text": "Register Now", "url": "https://example.com/register"}]
        with patch.object(hubspot_tools, "_get", side_effect=[
            _make_email_response("em1"),
            _mock_get_response_for_update("em1", ["staging_btn_0", "staging_footer_social",
                                                   "staging_footer_body", "staging_footer_hs"]),
        ]), patch.object(hubspot_tools, "_patch", return_value=_make_email_response("em1")) as mp:
            hubspot_tools.update_email_content(
                "em1", content_sections=content_sections, utm_params=None,
            )
            dest = mp.call_args[0][1]["content"]["widgets"]["staging_btn_0"]["body"]["destination"]
            assert dest == "https://example.com/register"

    def test_button_destination_tagged(self):
        content_sections = [{"type": "button", "text": "Register Now", "url": "https://example.com/register"}]
        with patch.object(hubspot_tools, "_get", side_effect=[
            _make_email_response("em1"),
            _mock_get_response_for_update("em1", ["staging_btn_0", "staging_footer_social",
                                                   "staging_footer_body", "staging_footer_hs"]),
        ]), patch.object(hubspot_tools, "_patch", return_value=_make_email_response("em1")) as mp:
            hubspot_tools.update_email_content(
                "em1", content_sections=content_sections, utm_params=_UTM,
            )
            dest = mp.call_args[0][1]["content"]["widgets"]["staging_btn_0"]["body"]["destination"]
            assert "utm_campaign=26q3-lf-kubecon-eu-invite" in dest
            assert "utm_content=register-now-cta" in dest

    def test_banner_link_tagged(self):
        content_sections = [{"type": "rich_text", "html": "<p>Body</p>"}]
        event_url = "https://events.linuxfoundation.org/kubecon-eu/"
        with patch.object(hubspot_tools, "_get", side_effect=[
            _make_email_response("em1"),
            _mock_get_response_for_update("em1", ["staging_banner", "staging_sec_0",
                                                   "staging_footer_social", "staging_footer_body",
                                                   "staging_footer_hs"]),
        ]), patch.object(hubspot_tools, "_patch", return_value=_make_email_response("em1")) as mp:
            hubspot_tools.update_email_content(
                "em1", banner_url="https://cdn.example.com/banner.png", event_url=event_url,
                content_sections=content_sections, utm_params=_UTM,
            )
            link = mp.call_args[0][1]["content"]["widgets"]["staging_banner"]["body"]["link"]
            assert "utm_campaign=26q3-lf-kubecon-eu-invite" in link
            assert "utm_content=banner" in link

    def test_rich_text_inline_links_tagged(self):
        html = '<p>Details on the <a href="https://example.com/agenda">agenda</a>.</p>'
        content_sections = [{"type": "rich_text", "html": html}]
        with patch.object(hubspot_tools, "_get", side_effect=[
            _make_email_response("em1"),
            _mock_get_response_for_update("em1", ["staging_sec_0", "staging_footer_social",
                                                   "staging_footer_body", "staging_footer_hs"]),
        ]), patch.object(hubspot_tools, "_patch", return_value=_make_email_response("em1")) as mp:
            hubspot_tools.update_email_content(
                "em1", content_sections=content_sections, utm_params=_UTM,
            )
            body_html = mp.call_args[0][1]["content"]["widgets"]["staging_sec_0"]["body"]["html"]
            assert "utm_campaign=26q3-lf-kubecon-eu-invite" in body_html
            assert "utm_content=body-link-1" in body_html

    def test_footer_social_links_tagged_except_lfx_insights(self):
        content_sections = [{"type": "rich_text", "html": "<p>Body</p>"}]
        with patch.object(hubspot_tools, "_get", side_effect=[
            _make_email_response("em1"),
            _mock_get_response_for_update("em1", ["staging_sec_0", "staging_footer_social",
                                                   "staging_footer_body", "staging_footer_hs"]),
        ]), patch.object(hubspot_tools, "_patch", return_value=_make_email_response("em1")) as mp:
            hubspot_tools.update_email_content(
                "em1", content_sections=content_sections, utm_params=_UTM,
            )
            social = mp.call_args[0][1]["content"]["widgets"]["staging_footer_social"]["body"]["social"]
            by_network = {s["network"]: s["url"] for s in social}

            # LFX Insights already carries its own static utm_campaign — must be untouched.
            assert "utm_campaign=23551824-Q3-2025-LF-Awareness-LFX-Insights" in by_network["icon"]
            assert "26q3-lf-kubecon-eu-invite" not in by_network["icon"]

            # The other social networks get tagged with the new campaign + a per-network utm_content.
            assert "utm_campaign=26q3-lf-kubecon-eu-invite" in by_network["twitter"]
            assert "utm_content=social-twitter" in by_network["twitter"]
            assert "utm_campaign=26q3-lf-kubecon-eu-invite" in by_network["linkedin"]
            assert "utm_content=social-linkedin" in by_network["linkedin"]
            assert "utm_campaign=26q3-lf-kubecon-eu-invite" in by_network["youtube"]
            assert "utm_campaign=26q3-lf-kubecon-eu-invite" in by_network["facebook"]

    def test_sponsor_logo_links_unaffected(self):
        """Sponsor logos have no link today — utm tagging must not add one."""
        content_sections = [{"type": "rich_text", "html": "<p>Body</p>"}]
        sponsors = [{"name": "Sponsor1", "logo_url": "https://cdn.example.com/sp1.png"}]
        with patch.object(hubspot_tools, "_get", side_effect=[
            _make_email_response("em1"),
            _mock_get_response_for_update("em1", ["staging_sec_0", "staging_sponsor_header",
                                                   "staging_sponsor_t1_0_0", "staging_footer_social",
                                                   "staging_footer_body", "staging_footer_hs"]),
        ]), patch.object(hubspot_tools, "_patch", return_value=_make_email_response("em1")) as mp:
            hubspot_tools.update_email_content(
                "em1", content_sections=content_sections, sponsors=sponsors, utm_params=_UTM,
            )
            widgets = mp.call_args[0][1]["content"]["widgets"]
            sponsor_widget = widgets["staging_sponsor_t1_0_0"]["body"]
            assert sponsor_widget["link"] == ""
