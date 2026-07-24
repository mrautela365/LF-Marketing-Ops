"""
Email-staging agent — plan / clone / content / chat turns.

All AI calls in this module go through `llm_gateway`, which owns the backend choice
(LiteLLM → Anthropic → Claude CLI) and enforces determinism (same model on every
backend, temperature=0, identical output shape). Do not call the Anthropic SDK or
the `claude` CLI directly here — add or change AI behavior via the gateway so it
stays consistent across all three backends.
"""
import json
import os
import subprocess
import asyncio
import nest_asyncio
nest_asyncio.apply()  # allows asyncio.run() inside FastAPI's event loop
from datetime import datetime
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, LITELLM_BASE_URL, LITELLM_API_KEY, HUBSPOT_PORTAL_ID
import hubspot_tools
import content_tools
from event_brands import lookup_event_brand
from stage_detector import detect_stage
import llm_gateway   # ALL AI calls route through this single deterministic gateway
import email_templates  # for template variants
import ai_email_templates  # for funnel-stage → AI-template mapping
import analyze_email_content  # for Variation A content analysis and optimization

# ── Shared system prompt ─────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an email staging assistant for Linux Foundation marketing operations.
You stage HubSpot marketing emails from event URLs through a 3-phase flow:

PHASE 1 - PLAN: User provides an event/campaign URL.
  1. Call fetch_url to extract event name, dates, organization, description from the URL.
  2. From those details, infer: brand (HubSpot brand name), email type, and email suffix.
  3. Call lookup_brand_history to get sender settings, send list, suppression lists.
  4. Build and present a complete Email Staging Plan — see format rules below.
  5. MESSAGING STRATEGY: After building the plan, call get_variant_strategies to see
     available messaging approaches (value-focused, urgency, social proof, etc.).
     Recommend one variant strategy based on the stage and audience, then ask the user
     if they want to use a different variant.

PHASE 2 - STAGE: User approves the plan (may provide missing fields, optional variant choice).
  1. If user chose a different variant, call select_template_variant with the variant_id.
  2. Call clone_email with the correct name.
  3. Call update_email_settings to apply from name, from address, email type, suppression lists.
  4. Return the HubSpot draft URL and ask for content.

PHASE 3 - CONTENT: User provides content (Google Doc URL, HTML, or text).
  1. Call fetch_content to convert to clean email HTML.
  2. Call update_email_content to update the email body.
  3. Return the final summary with draft link.

Plan format rules (STRICTLY follow):
  - NEVER mention cloning, source emails, or templates — only show the final staged settings.
  - Present as a clean summary with two sections:
    (a) A settings table with: Email Name, From Name, From Address, Email Type, Subject, Preview Text, Send Date
    (b) Audience section showing: Send List (with contact count if available), Suppression Lists
  - Mark fields that need user input as [REQUIRED — provide below]
  - Add a short paragraph summary at the top describing what will be staged.
  - After the plan table, ask ONLY for the specific missing fields.

Email naming convention:
  "<YY>Q<N> - <Brand> - <EventName> - <Suffix>"
  Examples: "26Q2 - CNCF - KubeCon EU - Invite", "26Q2 - OpenSSF - Newsletter - June"
  Quarter: Q1=Jan-Mar, Q2=Apr-Jun, Q3=Jul-Sep, Q4=Oct-Dec
  Suffix: Invite / Last Chance / Newsletter / Update / Reminder

Messaging Variants:
  Each marketing stage (Event Announcement, Registration Launch, etc.) has multiple
  messaging variants available (e.g., "value-focused", "urgency-focused", "social-proof").
  When you detect a stage, recommend a variant strategy, and the user can select it.
  Always call get_variant_strategies(stage_name) to see available options.

Best-Practice Templates:
  Proven B2B event email templates are available from ArgoCon/KeycloakCon analysis.
  These templates have documented open rates (45-52%) and CTR (10-22%).
  TEMPLATE TYPES:
    - B2B_Event_Announcement: Schedule/speaker launches (45% open rate)
    - B2B_Speaker_Conversion: Speaker to sponsor conversion (52% open rate)
    - B2B_Strategic_Close: Multi-event deals with pricing (48% open rate)
    - B2B_Rapid_Close: Existing accounts, quick close (35% open rate, 22% CTR)
    - B2B_Registration_Launch: Registration/CFP with urgency (40% open rate)

  IMPORTANT: In the PLAN phase, recommend the matching best-practice template
  with quality rating and expected performance metrics. Show the user WHICH
  template structure they should follow for this campaign type.

Safety rules (never violate):
  - NEVER delete, archive, or send any email or list.
  - NEVER modify any existing HubSpot list.
  - NEVER call update_email_settings or update_email_content on any email
    except the one created in the current session.
  - Always keep emails in DRAFT state.

Current date: {date}
HubSpot Portal: 8112310
"""

# ── Tool definitions (shared) ─────────────────────────────────────────────────

TOOLS = [
    {
        "name": "lookup_brand_history",
        "description": "Look up the most recently sent HubSpot email for a brand. Returns from name, from address, suppression list IDs, email type, and last email ID. Always call this first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "brand_name": {"type": "string"},
                "email_type_hint": {"type": "string", "description": "Optional: newsletter, event_invite, transactional"}
            },
            "required": ["brand_name"]
        },
    },
    {
        "name": "clone_email",
        "description": "Clone a HubSpot email with a new name. Returns new email ID and draft URL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_email_id": {"type": "string"},
                "clone_name": {"type": "string"}
            },
            "required": ["source_email_id", "clone_name"],
        },
    },
    {
        "name": "update_email_settings",
        "description": "Update email subject, preview text, from name/address, suppression list IDs, send list ID, email type.",
        "input_schema": {
            "type": "object",
            "properties": {
                "email_id": {"type": "string"},
                "subject": {"type": "string"},
                "preview_text": {"type": "string"},
                "from_name": {"type": "string"},
                "from_address": {"type": "string"},
                "suppression_list_ids": {"type": "array", "items": {"type": "string"}},
                "send_list_id": {"type": "string"},
                "email_type": {"type": "string"},
            },
            "required": ["email_id"],
        },
    },
    {
        "name": "update_email_content",
        "description": "Replace the email body with HTML. Auto-handles html_body and widget-module templates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "email_id": {"type": "string"},
                "html_content": {"type": "string"}
            },
            "required": ["email_id", "html_content"],
        },
    },
    {
        "name": "fetch_content",
        "description": "Convert a Google Doc URL, raw HTML, or plain text into clean email HTML.",
        "input_schema": {
            "type": "object",
            "properties": {"content_input": {"type": "string"}},
            "required": ["content_input"],
        },
    },
    {
        "name": "search_hubspot_lists",
        "description": "Search HubSpot contact lists by name.",
        "input_schema": {
            "type": "object",
            "properties": {"search_term": {"type": "string"}},
            "required": ["search_term"],
        },
    },
    {
        "name": "fetch_url",
        "description": (
            "Fetch an event or campaign URL and extract: event_name, brand_name, location, "
            "event_dates, description. Always call this first when given a URL."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"}
            },
            "required": ["url"],
        },
    },
    {
        "name": "search_emails_for_event",
        "description": (
            "Search HubSpot for the most recently sent email matching a brand + event name. "
            "Filters by short_brand_name (e.g. 'LF', 'CNCF') and scores by event_name keywords. "
            "Finds the same event's previous email for pre-populating settings."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "brand_name":       {"type": "string", "description": "Full brand name"},
                "event_name":       {"type": "string", "description": "Canonical event name"},
                "location":         {"type": "string", "description": "Location hint (optional)"},
                "short_brand_name": {"type": "string", "description": "Short brand code, e.g. LF, CNCF, PTF"},
                "event_short_name": {"type": "string", "description": "Short event name, e.g. OSS Japan, KubeCon EU"},
                "email_type":       {"type": "string", "description": "Email suffix hint: Invite, Last Chance, Newsletter, Reminder, Update"},
            },
            "required": ["brand_name", "event_name"],
        },
    },
    {
        "name": "get_variant_strategies",
        "description": (
            "Get available messaging variant strategies for a marketing stage. "
            "Returns list of variants with id, label, and strategy description. "
            "Call this after detecting the event stage to recommend a variant to the user."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "stage_name": {"type": "string", "description": "Marketing stage (e.g., 'Event Announcement', 'Registration Launch', 'Final Countdown')"}
            },
            "required": ["stage_name"],
        },
    },
    {
        "name": "select_template_variant",
        "description": (
            "Select a specific messaging variant for a stage. "
            "Call this when the user chooses a different variant from the recommended one."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "stage_name": {"type": "string", "description": "Marketing stage"},
                "variant_id": {"type": "string", "description": "Variant ID (e.g., 'v1_value_focused', 'v2_urgency_focused')"},
                "reason": {"type": "string", "description": "Why this variant was selected (for logging)"}
            },
            "required": ["stage_name", "variant_id"],
        },
    },
    {
        "name": "get_recommended_template",
        "description": (
            "Get the best-practice B2B template recommendation for a campaign type. "
            "Returns template key, quality rating (1-5 stars), expected open rate, CTR, and strategy. "
            "Call this in PLAN phase to show which best-practice template to follow."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "campaign_type": {"type": "string", "description": "Campaign type: announcement, speaker_conversion, multi_event_deal, existing_account_close, or registration_launch"}
            },
            "required": ["campaign_type"],
        },
    },
    {
        "name": "get_template_by_key",
        "description": (
            "Get a best-practice template by its key (e.g., 'B2B_Event_Announcement'). "
            "Returns the full template with subject, preheader, body, and placeholders. "
            "Use this in CONTENT phase when creating Variant B to get the template to fill."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "template_key": {"type": "string", "description": "Template key (e.g., 'B2B_Event_Announcement', 'B2B_Speaker_Conversion')"}
            },
            "required": ["template_key"],
        },
    },
]

# ── Tool executor (shared by both modes) ──────────────────────────────────────

import logging
_log = logging.getLogger("email-staging.agent")
_log.setLevel(logging.INFO)
if not _log.handlers:
    _lh = logging.StreamHandler()
    _lh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
    _log.addHandler(_lh)
    _log.propagate = False

# Tracks email IDs cloned in the current session — only these IDs may be modified.
# Set by clone_email tool call, checked before any update operation.
# For A/B testing: session can create Variant A (in clone_turn) and Variant B (in content_turn).
# NOTE: This is per-process, not per-session. Use session.meta["email_id"] as the
# authoritative source; this global is a fallback.
_session_email_id: str | None = None
_session_email_ids_allowed: set[str] = set()  # For A/B testing: track both Variant A and Variant B

# Tools that are completely forbidden regardless of inputs
_FORBIDDEN_TOOLS = {"delete_email", "delete_list", "delete_contact", "archive_email"}

# Tools that perform write operations on HubSpot — must be validated
_WRITE_TOOLS = {"update_email_settings", "update_email_content"}


def _execute_tool(name: str, inputs: dict, session_email_id: str | None = None) -> str:
    global _session_email_id, _session_email_ids_allowed
    _log.info(f"  → TOOL {name}({', '.join(f'{k}={str(v)[:40]!r}' for k,v in inputs.items())})")

    # ── Safety gate 1: block any delete/archive tools outright ──────────────
    if name in _FORBIDDEN_TOOLS:
        _log.warning(f"  ✗ BLOCKED forbidden tool: {name}")
        return json.dumps({"error": f"Tool '{name}' is not permitted. This service never deletes or archives."})

    # ── Safety gate 2: write ops only allowed on emails cloned this session ──
    if name in _WRITE_TOOLS:
        target_id = inputs.get("email_id")
        # Allow if: session_email_id provided (explicit param) OR in allowed set (for A/B testing)
        allowed_ids = _session_email_ids_allowed | ({session_email_id} if session_email_id else {_session_email_id} if _session_email_id else set())
        if not allowed_ids:
            return json.dumps({"error": "No email has been cloned in this session yet. Clone first."})
        if target_id not in allowed_ids:
            _log.warning(f"  ✗ BLOCKED write to email {target_id} — only {allowed_ids} are allowed this session")
            return json.dumps({
                "error": f"Write blocked: email {target_id} was not created by this session. "
                         f"Only emails {allowed_ids} (cloned in this session) may be modified."
            })

    try:
        if name == "lookup_brand_history":
            result = hubspot_tools.lookup_brand_history(
                inputs["brand_name"],
                email_type_hint=inputs.get("email_type_hint")
            )
        elif name == "clone_email":
            result = hubspot_tools.clone_email(inputs["source_email_id"], inputs["clone_name"])
            # Register the newly created email ID for A/B testing (allow both Variant A and B)
            new_email_id = result.get("email_id")
            _session_email_id = new_email_id  # Keep for backward compatibility
            _session_email_ids_allowed.add(new_email_id)  # Add to allowed set for A/B testing
            _log.info(f"  ✓ Session email allowed: {new_email_id} (all allowed: {_session_email_ids_allowed})")
        elif name == "update_email_settings":
            email_id = inputs.pop("email_id")
            result = hubspot_tools.update_email_settings(email_id, **inputs)
        elif name == "update_email_content":
            result = hubspot_tools.update_email_content(inputs["email_id"], inputs["html_content"])
        elif name == "fetch_content":
            html = content_tools.prepare_content(inputs["content_input"])
            result = {"html": html, "length": len(html)}
        elif name == "search_hubspot_lists":
            result = hubspot_tools.search_hubspot_lists(inputs["search_term"])
        elif name == "fetch_url":
            result = content_tools.scrape_event_full(inputs["url"])
        elif name == "search_emails_for_event":
            result = hubspot_tools.search_emails_for_event(
                inputs["brand_name"],
                inputs["event_name"],
                inputs.get("location", ""),
                short_brand_name=inputs.get("short_brand_name", ""),
                event_short_name=inputs.get("event_short_name", ""),
                email_type=inputs.get("email_type", ""),
            )
        elif name == "get_variant_strategies":
            stage_name = inputs.get("stage_name")
            strategies = email_templates.list_variant_strategies(stage_name)
            if strategies:
                result = {"stage": stage_name, "variants": strategies, "found": True}
            else:
                result = {"stage": stage_name, "found": False, "error": f"No variants found for stage '{stage_name}'"}
        elif name == "select_template_variant":
            stage_name = inputs.get("stage_name")
            variant_id = inputs.get("variant_id")
            reason = inputs.get("reason", "User selected")
            variant = email_templates.get_template_variant(stage_name, variant_id)
            if variant:
                result = {"selected": True, "stage": stage_name, "variant_id": variant_id, "reason": reason}
                _log.info(f"  ✓ Selected variant {variant_id} for stage {stage_name}: {reason}")
            else:
                result = {"selected": False, "error": f"Variant '{variant_id}' not found for stage '{stage_name}'"}
        elif name == "get_recommended_template":
            campaign_type = inputs.get("campaign_type")
            recommendation = email_templates.recommend_best_practice_template(campaign_type)
            if recommendation and recommendation.get("template"):
                template = recommendation["template"]
                result = {
                    "found": True,
                    "campaign_type": campaign_type,
                    "template_key": recommendation.get("key", ""),
                    "quality_rating": template.get("quality_rating", 0),
                    "expected_open_rate": template.get("key_metrics", {}).get("expected_open_rate", 0),
                    "expected_ctr": template.get("key_metrics", {}).get("expected_ctr", 0),
                    "source": template.get("source", "Unknown"),
                    "strategy": template.get("template", {}).get("strategy", ""),
                    "label": template.get("template", {}).get("label", "Unknown")
                }
                _log.info(f"  ✓ Recommended template for '{campaign_type}': {result['label']}")
            else:
                result = {"found": False, "campaign_type": campaign_type, "error": f"No template found for campaign type '{campaign_type}'"}
        elif name == "get_template_by_key":
            template_key = inputs.get("template_key")
            template = email_templates.get_best_practice_template(template_key)
            if template:
                template_obj = template.get("template", {})
                result = {
                    "found": True,
                    "template_key": template_key,
                    "label": template_obj.get("label", "Unknown"),
                    "strategy": template_obj.get("strategy", ""),
                    "subject": template_obj.get("subject", ""),
                    "preheader": template_obj.get("preheader", ""),
                    "body": template_obj.get("body", ""),
                    "quality_rating": template.get("quality_rating", 0),
                    "expected_open_rate": template.get("key_metrics", {}).get("expected_open_rate", 0),
                    "expected_ctr": template.get("key_metrics", {}).get("expected_ctr", 0),
                }
                _log.info(f"  ✓ Retrieved template: {result['label']}")
            else:
                result = {"found": False, "template_key": template_key, "error": f"Template '{template_key}' not found"}
        else:
            result = {"error": f"Unknown tool: {name}. Allowed: lookup_brand_history, clone_email, "
                               "update_email_settings, update_email_content, fetch_content, search_hubspot_lists, "
                               "get_variant_strategies, select_template_variant, get_recommended_template, get_template_by_key"}
    except Exception as exc:
        result = {"error": str(exc)}
    return json.dumps(result)


# ── Agentic turns now run through llm_gateway.run_agent (see run_turn below) ──
# The former _sdk_run_turn (Anthropic SDK loop) and _sdk_run_turn_cc (Claude CLI
# text-protocol loop) were removed. Both backends are handled identically by the
# gateway, which pins model + temperature=0 and normalizes the output shape.


# ── Single-turn Claude helper (no tools, plain text) ─────────────────────────

def _claude_text(prompt: str, max_tokens: int = 100, timeout: int = 60) -> str:
    """Single-shot text (no tools). Deterministic on every backend via the gateway."""
    return llm_gateway.complete_text(prompt, max_tokens=max_tokens, timeout=timeout)


def _format_ab_test_comparison(variant_a_info: dict, variant_b_info: dict) -> str:
    """
    Format Version A vs Version B comparison for display.

    Args:
        variant_a_info: {email_id, subject, from_name, from_address, type}
        variant_b_info: {email_id, subject, template_key, quality_rating, expected_open_rate, expected_ctr, strategy}

    Returns:
        Nicely formatted comparison string
    """
    # Format rating stars
    quality_rating = variant_b_info.get("quality_rating", 5)
    stars = "★" * quality_rating + "☆" * (5 - quality_rating)

    # Format expected metrics
    expected_open_rate = int(variant_b_info.get("expected_open_rate", 0) * 100)
    expected_ctr = int(variant_b_info.get("expected_ctr", 0) * 100)

    comparison = f"""
════════════════════════════════════════════════════════════════════════════════
✅ BOTH VARIANTS READY FOR A/B TESTING IN HUBSPOT
════════════════════════════════════════════════════════════════════════════════

🔄 SIDE-BY-SIDE COMPARISON

VERSION A (User-Created Content)          VERSION B (Best-Practice Template)
─────────────────────────────────────────────────────────────────────────────
Email ID:         {variant_a_info.get('email_id', 'N/A'):<20} {variant_b_info.get('email_id', 'N/A')}
Subject Line:     {variant_a_info.get('subject', 'N/A')[:35]:<20} {variant_b_info.get('subject', 'N/A')[:35]}
Type:             User-Generated          {variant_b_info.get('template_key', 'Template')}
Quality Rating:   Unknown                 {stars} ({quality_rating}/5)
Expected Open:    Unknown                 {expected_open_rate}% (vs 25% industry avg)
Expected CTR:     Unknown                 {expected_ctr}% (vs 8% industry avg)
Source:           Your Content            ArgoCon + KeycloakCon 2026
─────────────────────────────────────────────────────────────────────────────

📊 VERSION A DETAILS (Your Content)
  Email ID: {variant_a_info.get('email_id', 'N/A')}
  Subject: {variant_a_info.get('subject', 'N/A')}
  From: {variant_a_info.get('from_name', 'N/A')} <{variant_a_info.get('from_address', 'N/A')}>
  Status: DRAFT (ready to send)
  Type: User-created messaging
  HubSpot Link: https://app.hubspot.com/content/emails/{variant_a_info.get('email_id', '')}

📋 VERSION B DETAILS (Proven Template)
  Email ID: {variant_b_info.get('email_id', 'N/A')}
  Subject: {variant_b_info.get('subject', 'N/A')}
  Template: {variant_b_info.get('template_key', 'Unknown')} {stars}
  From: {variant_a_info.get('from_name', 'N/A')} <{variant_a_info.get('from_address', 'N/A')}>
  Status: DRAFT (ready to send)
  Strategy: {variant_b_info.get('strategy', 'Unknown')}
  Expected Metrics: {expected_open_rate}% open, {expected_ctr}% CTR
  HubSpot Link: https://app.hubspot.com/content/emails/{variant_b_info.get('email_id', '')}

════════════════════════════════════════════════════════════════════════════════
🚀 NEXT STEP: CREATE A/B TEST IN HUBSPOT
════════════════════════════════════════════════════════════════════════════════

1. Go to HubSpot → Campaigns → Settings
2. Scroll to "A/B Test" section
3. Click "Create A/B Test"
4. Configure:
   - Variant A: Email ID {variant_a_info.get('email_id', 'N/A')}
   - Variant B: Email ID {variant_b_info.get('email_id', 'N/A')}
   - Split: 50/50
   - Test Variable: Subject Line (Recommended)
5. Send test to audience
6. Monitor results in Campaign Analytics

WHAT TO EXPECT:
  ✓ Variant A: Unknown performance (user content)
  ✓ Variant B: ~{expected_open_rate}% open rate (proven ArgoCon template)
  ✓ Test Duration: 24-48 hours minimum
  ✓ Auto-select winner: Yes (automatically sends winner to remaining contacts)

════════════════════════════════════════════════════════════════════════════════
"""
    return comparison


def _fill_template_placeholders(template_text: str, event_data: dict) -> str:
    """Fill template placeholders with actual event data."""
    if not template_text:
        return ""

    text = template_text
    # Replace placeholders from event_data
    event_name = event_data.get("event_name", "Event")
    event_dates = event_data.get("event_dates", [])
    date_range = ", ".join(event_dates) if event_dates else "TBD"
    location = event_data.get("location", "TBD")

    text = text.replace("[Event Name]", event_name)
    text = text.replace("[Dates]", date_range)
    text = text.replace("[City]", location)
    text = text.replace("[Date]", event_dates[0] if event_dates else "TBD")

    return text


def _get_variant_subject_preview(stage_name: str, variant_id: str | None, event_data: dict) -> tuple[str, str]:
    """
    Get subject and preview text for a variant.
    Returns (subject, preview_text) filled with event data.
    """
    # Get variant, default to first if not specified
    variant = email_templates.get_template_variant(stage_name, variant_id) if variant_id else email_templates.get_template(stage_name)

    if not variant:
        return "", ""

    subject = _fill_template_placeholders(variant.get("subject", ""), event_data)
    preview = _fill_template_placeholders(variant.get("preheader", ""), event_data)

    return subject, preview


def _recommend_best_practice_template(campaign_type: str, context: dict = None) -> dict | None:
    """
    Recommend best-practice B2B template based on campaign type.

    Campaign types:
    - announcement: Event schedule/announcement
    - speaker_conversion: Speaker to sponsor conversion
    - multi_event_deal: Multiple events, complex deal
    - existing_account_close: Quick close for existing accounts
    - registration_launch: Registration/CFP launch with deadline

    Returns: {key, template, quality_rating, source, recommendation_reason}
    """
    recommendation = email_templates.recommend_best_practice_template(campaign_type)

    if recommendation:
        reason_map = {
            "announcement": "Proven 45% open rate, relationship-focused structure",
            "speaker_conversion": "Proven 52% open rate, achievement → sponsorship flow",
            "multi_event_deal": "Proven transparent pricing, comprehensive value prop",
            "existing_account_close": "Proven 22% CTR, minimal friction approach",
            "registration_launch": "Proven 40% open rate, conversational + urgent",
        }

        return {
            **recommendation,
            "recommendation_reason": reason_map.get(campaign_type, "Industry best practice"),
            "context": context or {}
        }
    return None


def _compare_with_similar_emails(stage_name: str, campaign_context: dict = None) -> dict:
    """
    Compare current email with similar templates to find best match.

    Returns analysis of:
    - Recommended template from best-practice collection
    - Quality rating (0-5)
    - Why this template is recommended
    - Key success factors from the template
    """
    campaign_type_map = {
        "Event Announcement": "announcement",
        "Registration Launch": "registration_launch",
        "CFP Launch": "registration_launch",
        "Schedule Announcement": "announcement",
        "Final Countdown": "registration_launch",
    }

    campaign_type = campaign_type_map.get(stage_name, "announcement")
    recommendation = _recommend_best_practice_template(campaign_type, campaign_context)

    return {
        "stage": stage_name,
        "campaign_type": campaign_type,
        "recommended_template": recommendation,
        "comparison_notes": f"This {stage_name} campaign matches B2B best practices. "
                           f"Recommended to follow {recommendation['key'] if recommendation else 'standard'} template structure.",
    }


def _recommend_variant_strategy(stage_name: str, days_to_event: int | None = None, audience_type: str = "tech") -> tuple[str, str]:
    """
    Recommend a variant strategy based on stage and event proximity.
    Returns (variant_id, reason_description).
    """
    strategies = {
        # Event Announcement: early stage, focus on value + community
        "Event Announcement": ("v1_value_focused", "Emphasizes learning opportunities and community value — good for early awareness"),

        # Registration Launch: mid-funnel, mix value + urgency
        "Registration Launch": ("v1_discount_focused", "Leads with early bird savings and urgency — proven to drive registrations"),

        # Schedule Announcement: mid-late, can be varied
        "Schedule Announcement": ("v1_keynote_focused", "Highlights speaker lineup — strong draw for tech audiences"),

        # Main Registration Push: urgency-focused
        "Main Registration Push": ("v1_discount_focused", "Emphasizes savings ending soon — drives last-minute conversions"),

        # Final Countdown: pure urgency + FOMO
        "Final Countdown": ("v1_fomo_urgency", "Hard deadline + fear of missing out — final push strategy"),

        # CFP stages: speaker-focused
        "CFP Launch": ("v1_main", "Standard call-for-proposals announcement"),

        # Post-event: social proof + community
        "Thank You + Survey": ("v1_main", "Standard thank you with survey request"),

        # Default for any unlisted stages
    }

    default_variant = strategies.get(stage_name, ("v1_main", "Standard template variant"))
    return default_variant


def _format_variant_recommendations(stage_name: str) -> str:
    """Format variant strategies for display in plan output."""
    strategies = email_templates.list_variant_strategies(stage_name)
    if not strategies:
        return ""

    lines = ["**Messaging Strategy Options:**"]
    for v in strategies:
        lines.append(f"  - **{v['id']}** ({v['label']}): {v['strategy']}")

    recommended_id, reason = _recommend_variant_strategy(stage_name)
    lines.append(f"\n*Recommended: {recommended_id} — {reason}*")
    lines.append("*Feel free to use a different variant if you prefer a different messaging approach.*")

    return "\n".join(lines)


def fetch_asana_task_via_mcp(task_url: str) -> dict:
    """
    Fetch Asana task + subtask data via the Asana MCP connector (Claude Code subprocess).
    Used when ASANA_ACCESS_TOKEN is not set — requires the Asana MCP to be authenticated
    in the parent Claude Code session.
    Returns the same shape as asana_tools.extract_brief().
    """
    import re as _re

    prompt = f"""Use the Asana MCP tools to fetch task data and return it as a JSON object.

Asana task URL: {task_url}

Steps:
1. Extract the task GID from the URL (it is the numeric ID after /task/)
2. Call get_task with that GID requesting fields: name, notes, due_on, projects
3. Call get_tasks or a subtask lookup to list subtasks of this task (fields: name, notes, gid)
4. For any subtask named "Content" or "List Pull", read its notes carefully for URLs and instructions

Return ONLY this JSON (no markdown fences, no explanation — raw JSON only):
{{
  "task_name": "<full parent task name>",
  "brand_name": "<brand from task name pattern 'YYQn - BRAND - ...' — or empty string>",
  "content_doc_url": "<first docs.google.com/document URL found in Content subtask, or empty string>",
  "event_url": "<first LF event URL (linuxfoundation.org / cncf.io / etc.) found anywhere, or empty string>",
  "audience_instructions": "<text from List Pull subtask notes, or empty string>",
  "due_on": "<due date YYYY-MM-DD, or empty string>",
  "subtask_names": ["subtask name 1", "subtask name 2"]
}}"""

    # MCP tools are only reachable via the Claude Code CLI (not the SDK backends),
    # so this always uses the CLI path — still model-pinned by the gateway.
    raw, success = llm_gateway.run_cli_skill(prompt, timeout=180)
    if not success:
        raise RuntimeError("Asana MCP fetch failed (Claude CLI returned non-zero).")

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0].strip()

    m = _re.search(r'\{[\s\S]+\}', raw)
    if not m:
        raise ValueError(f"MCP fetch returned no JSON. Response was: {raw[:300]}")

    data = json.loads(m.group(0))
    data.setdefault("email_name", data.get("task_name", ""))
    data.setdefault("subtask_names", [])
    return data


import re as _re

# Patterns that Claude should never emit in rich_text sections — the system adds them.
_STRIP_PATTERNS = [
    # "Thank You to Our Sponsors!" heading
    r'<[^>]+>[^<]*[Tt]hank [Yy]ou to [Oo]ur [Ss]ponsors[!]?[^<]*</[^>]+>',
    # "This email was sent by: ..." footer line
    r'<[^>]+>[^<]*[Tt]his email was sent by[^<]*</[^>]+>',
    # "Subscription Center" or "Unsubscribe" footer paragraphs
    r'<[^>]+>[^<]*[Uu]nsubscribe[^<]*</[^>]+>',
    r'<[^>]+>[^<]*[Ss]ubscription [Cc]enter[^<]*</[^>]+>',
    # LF address footer
    r'<[^>]+>[^<]*2810 N Church[^<]*</[^>]+>',
    r'<[^>]+>[^<]*Wilmington, Delaware[^<]*</[^>]+>',
    # "View in browser" header link — HubSpot adds this automatically; never put it in body content
    r'<[^>]+>[^<]*[Vv]iew (?:this )?(?:email )?in (?:your )?[Bb]rowser[^<]*</[^>]+>',
    r'<a[^>]*>[^<]*[Vv]iew in [Bb]rowser[^<]*</a>',
]
_STRIP_RE = _re.compile("|".join(_STRIP_PATTERNS), _re.IGNORECASE)


def _strip_system_content(html: str) -> str:
    """Remove headings/lines that the system adds automatically (sponsors, footer, sent-by)."""
    return _STRIP_RE.sub("", html).strip()


# Whole rich_text sections to drop outright rather than try to patch in place.
# Reference emails used for style-learning are themselves past outputs of this
# same pipeline, so their stored content already contains these system-injected
# blocks (sponsor thank-you/tier callouts, "FOLLOW US", footer text) — the model
# has no way to tell they're system-injected and will copy them as ordinary body
# content. _STRIP_RE above tries to excise these via tag-matching regex, but that
# only touches the throwaway UI preview HTML and is fragile against the nested
# <span>/<br> markup Claude actually emits (it silently fails to match). This
# check instead strips all tags to plain text before matching, and drops the
# whole section — applied to the real `sections` array (not just the preview),
# since that array is what's sent to HubSpot via content_sections.
_SECTION_FORBIDDEN_PHRASES = (
    "thank you to our sponsors", "check out all our sponsors", "follow us",
    "view in browser", "view this email in", "view email in browser",
    "unsubscribe", "subscription center",
    "2810 n church", "wilmington, delaware",
    "this email was sent by",
)

# Sponsor tier labels — "gold"/"silver" are too generic for a substring match
# (would false-positive on legitimate copy like "gold standard support"), so
# these only match when they're the section's ENTIRE content — i.e. a bare
# tier heading with nothing else, which is unambiguously a sponsor-tier artifact.
_SECTION_FORBIDDEN_EXACT = {
    "platinum", "gold", "silver", "bronze",
    "platinum sponsors", "gold sponsors", "silver sponsors", "bronze sponsors",
}


def _drop_system_sections(sections: list, sponsors: list = None) -> list:
    """Drop rich_text sections that duplicate system-injected content (sponsors,
    follow-us, footer). See _SECTION_FORBIDDEN_PHRASES for why this is needed.

    Also drops any section that names a known sponsor — "Do NOT include sponsor
    names" is already an explicit instruction to the model, so a section naming
    one is always a violation of that rule, not a legitimate edge case to keep.
    """
    sponsor_names = tuple(
        s["name"].strip().lower()
        for s in (sponsors or [])
        if isinstance(s, dict) and s.get("name", "").strip()
    )
    out = []
    for sec in sections:
        if sec.get("type") == "rich_text":
            plain = _re.sub(r"<[^>]+>", " ", sec.get("html", "") or "").lower()
            stripped = plain.strip()
            if any(p in plain for p in _SECTION_FORBIDDEN_PHRASES):
                continue
            if stripped in _SECTION_FORBIDDEN_EXACT:
                continue
            if any(name in plain for name in sponsor_names):
                continue
        out.append(sec)
    return out


def _sections_to_html(sections: list, btn_color: str = "#04c0da",
                      sponsors: list = None) -> str:
    """Convert structured sections array to flat HTML for the UI iframe preview."""
    parts = []
    for sec in sections:
        stype = sec.get("type", "")
        if stype == "rich_text":
            html = _strip_system_content(sec.get("html", "").strip())
            if html:
                parts.append(f'<div style="padding:15px 40px 10px;">{html}</div>')
        elif stype == "button":
            text  = sec.get("text", "")
            url   = sec.get("url", "#")
            color = sec.get("color") or btn_color
            parts.append(
                f'<div style="text-align:center;padding:5px 20px;">'
                f'<table cellpadding="0" cellspacing="0" border="0" style="margin:0 auto;">'
                f'<tr><td style="background-color:{color};border-radius:8px;'
                f'padding:12px 24px;text-align:center;">'
                f'<a href="{url}" style="color:#ffffff;font-weight:bold;font-size:16px;'
                f'text-decoration:none;font-family:Arial,sans-serif;">{text}</a>'
                f'</td></tr></table></div>'
            )
    # Sponsors — each tier shows up to 5 logos as 3 in the first row + 2 in the
    # second. Tier 1 larger, Tier 2 smaller. Only sponsors with a logo are shown.
    _per_tier = 5
    _logo_sponsors = [s for s in (sponsors or []) if isinstance(s, dict) and s.get("logo_url")]
    _tier1 = _logo_sponsors[:_per_tier]                 # top tier — larger
    _tier2 = _logo_sponsors[_per_tier:_per_tier * 2]    # next tier — smaller

    def _sponsor_rows_html(items, height, max_w, cell_pad):
        """Render a tier as centered rows: 3 in the first row, 2 in the second."""
        rows_html = []
        items = items[:_per_tier]
        _rows = [items[:3], items[3:5]] if len(items) > 3 else [items]
        for row in _rows:
            if not row:
                continue
            cells = "".join(
                f'<td style="padding:{cell_pad};text-align:center;vertical-align:middle;">'
                f'<img src="{s["logo_url"]}" alt="{s.get("name","Sponsor")}" '
                f'height="{height}" style="max-width:{max_w}px;max-height:{height}px;'
                f'height:auto;width:auto;object-fit:contain;display:inline-block;"></td>'
                for s in row
            )
            rows_html.append(
                f'<table cellpadding="0" cellspacing="0" border="0" '
                f'style="margin:6px auto 0;"><tr>{cells}</tr></table>'
            )
        return "\n".join(rows_html)

    if _tier1:
        parts.append(
            '<div style="padding:10px 40px;">'
            '<hr style="border:none;border-top:1px solid #eee;margin:10px 0;">'
            '</div>'
            '<p style="font-weight:bold;text-align:center;font-size:18px;'
            'padding:0 40px;margin:0 0 10px;">Thank You to Our Sponsors!</p>'
        )
        parts.append(_sponsor_rows_html(_tier1, 60, 180, "8px 16px"))
        if _tier2:
            parts.append(_sponsor_rows_html(_tier2, 45, 140, "6px 12px"))
    return "\n".join(parts)


def _build_email_preview(banner_url: str, body_html: str,
                         event_url: str = "", event_name: str = "") -> str:
    """Build a standalone preview HTML email for display in the browser iframe."""
    if banner_url:
        link_open  = ('<a href="' + event_url + '" target="_blank" style="display:block;line-height:0;font-size:0;">') if event_url else ""
        link_close = "</a>" if event_url else ""
        banner_row = (
            '<tr><td style="background-color:#003366;text-align:center;padding:0;line-height:0;font-size:0;">'
            + link_open
            + '<img src="' + banner_url + '" width="600" alt="' + event_name + '"'
            + ' style="display:block;width:100%;max-width:600px;height:auto;">'
            + link_close
            + "</td></tr>"
        )
    else:
        banner_row = '<tr><td style="background-color:#003366;height:8px;"></td></tr>'

    return (
        "<!DOCTYPE html><html><head>"
        '<meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1.0">'
        # Guard: any image (hero, inline body, reference) is capped to the column
        # width so it can never overflow the preview. Inline styles (system hero,
        # sponsor logos) still win for their own sizing.
        "<style>img{max-width:100%;height:auto;} table{max-width:100%;}</style>"
        "</head>"
        '<body style="margin:0;padding:0;background-color:#F4F4F4;font-family:Arial,sans-serif;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'
        ' style="background-color:#F4F4F4;">'
        '<tr><td align="center" style="padding:20px 0;">'
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"'
        ' style="max-width:600px;width:100%;background-color:#ffffff;'
        'border-radius:4px;overflow:hidden;">'
        + banner_row
        + "<tr><td>" + body_html + "</td></tr>"
        # ── Pre-footer divider ──────────────────────────────────────────
        + '<tr><td style="padding:0 40px;">'
        '<hr style="border:none;border-top:1px solid #23496d;margin:20px 0 0;">'
        "</td></tr>"
        # ── Social icons row (CSS circles — no external image dependency) ─
        + '<tr><td style="background-color:#ffffff;padding:16px 40px;text-align:center;">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0"'
        ' style="margin:0 auto;">'
        "<tr>"
        # LFX
        '<td style="padding:0 6px;">'
        '<a href="https://insights.linuxfoundation.org/'
        '?utm_campaign=23551824-Q3-2025-LF-Awareness-LFX-Insights'
        '&amp;utm_source=email&amp;utm_medium=LF-Events&amp;utm_content=regular-email"'
        ' target="_blank" style="display:inline-block;width:32px;height:32px;'
        'background-color:#09c0d9;border-radius:50%;color:#ffffff;text-align:center;'
        'line-height:32px;text-decoration:none;font-weight:bold;font-size:11px;'
        'font-family:Arial,sans-serif;">LFX</a></td>'
        # Twitter / X
        '<td style="padding:0 6px;">'
        '<a href="https://twitter.com/linuxfoundation" target="_blank"'
        ' style="display:inline-block;width:32px;height:32px;background-color:#000000;'
        'border-radius:50%;color:#ffffff;text-align:center;line-height:32px;'
        'text-decoration:none;font-weight:bold;font-size:14px;'
        'font-family:Arial,sans-serif;">𝕏</a></td>'
        # LinkedIn
        '<td style="padding:0 6px;">'
        '<a href="https://www.linkedin.com/company/the-linux-foundation/" target="_blank"'
        ' style="display:inline-block;width:32px;height:32px;background-color:#0077b5;'
        'border-radius:50%;color:#ffffff;text-align:center;line-height:32px;'
        'text-decoration:none;font-weight:bold;font-size:13px;'
        'font-family:Arial,sans-serif;">in</a></td>'
        # Facebook
        '<td style="padding:0 6px;">'
        '<a href="https://www.facebook.com/TheLinuxFoundation/" target="_blank"'
        ' style="display:inline-block;width:32px;height:32px;background-color:#1877f2;'
        'border-radius:50%;color:#ffffff;text-align:center;line-height:32px;'
        'text-decoration:none;font-weight:bold;font-size:16px;'
        'font-family:Arial,sans-serif;">f</a></td>'
        "</tr></table>"
        "</td></tr>"
        # ── "Sent by" text ──────────────────────────────────────────────
        + '<tr><td style="background-color:#ffffff;padding:0 40px 8px;text-align:center;">'
        '<p style="margin:0;font-size:12px;line-height:175%;color:#000000;">'
        "This email was sent by: "
        '<strong>The Linux Foundation Events</strong>'
        "</p>"
        "</td></tr>"
        # ── Address + subscription center ───────────────────────────────
        + '<tr><td style="background-color:#ffffff;padding:0 40px 24px;text-align:center;">'
        '<p style="margin:0 0 6px;font-size:12px;line-height:150%;color:#666666;">'
        "The Linux Foundation, 2810 N Church St., PMB 57274,<br>"
        "Wilmington, Delaware 19802-4447, United States"
        "</p>"
        '<p style="margin:0;font-size:12px;">'
        '<a href="{{ unsubscribe_link }}"'
        ' style="color:#0094ff;text-decoration:underline;">Subscription Center</a>'
        "</p>"
        "</td></tr>"
        "</table></td></tr></table></body></html>"
    )


def generate_email_content(
    event_details: dict,
    stage_info: dict,
    brand_history: dict | None,
    change_request: str = "",
    source_email_id: str = "",
    reference_ids: list = None,
) -> dict:  # noqa: C901
    """
    Generate subject, preview text, and full HTML email body.

    Primary mode: reads the ACTUAL CONTENT of the top reference emails (up to 3)
    for this brand/stage, picks the richest one as the structural template, and
    learns the house STYLE & TONE from all of them. Claude then produces a similar
    email for the new event — same structure, voice, and style; all event-specific
    content (name, dates, speakers, sponsors) substituted.

    reference_ids: ranked list (best first) of candidate reference email IDs. The
      function reads each, chooses the primary by content richness, and uses the
      rest as additional style/tone references. Falls back to [source_email_id]
      when reference_ids is not supplied (skill path / backward compatibility).

    Fallback: if no reference email is available, falls back to the official
    Marketing Journey stage template.

    Returns: {subject, preview_text, html, body_html, banner_url}
    """
    import re as _re
    import logging as _logging
    _log = _logging.getLogger("email-staging")

    event_name    = event_details.get("event_name", "")
    event_dates   = event_details.get("event_dates", [])
    location      = event_details.get("location", "")
    description   = (event_details.get("description") or "")[:400]
    url           = event_details.get("url", "")
    hero_img      = event_details.get("hero_image_url", "")
    logo_img      = event_details.get("logo_url", "")
    speakers      = event_details.get("speakers", [])
    topics        = event_details.get("topics", [])
    sponsors      = event_details.get("sponsors", [])[:10]   # 2 tiers × 5 (3+2 each)
    reg           = event_details.get("registration") or {}

    stage_name         = stage_info.get("name", "")
    funnel             = stage_info.get("funnel", "")
    cta_label          = stage_info.get("cta_label", "Register Now")
    event_date         = stage_info.get("event_date_str", "") or (event_dates[0] if event_dates else "")
    from_name          = (brand_history or {}).get("from_name") or "Linux Foundation Events"
    dates_display      = event_dates[0] if event_dates else event_date
    marketing_strategy = stage_info.get("marketing_strategy", "")
    content_ideas      = stage_info.get("content_ideas", [])

    # Date awareness — the email is written NOW, so any expired pricing window or
    # past deadline (often copied verbatim from the reference email / event page)
    # must be dropped. Give Claude today's date and an explicit exclusion rule.
    _today_str = datetime.now().strftime("%B %d, %Y")
    date_rule = (
        "━━━ CRITICAL — DATE AWARENESS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Today's date is {_today_str}. "
        f"The event takes place on {event_date or dates_display or 'the date above'}.\n"
        "- NEVER include any registration tier, early-bird price, deadline, or date that\n"
        "  has ALREADY PASSED relative to today — even if it appears in the reference\n"
        "  email or event details. Drop expired windows entirely; do not copy them.\n"
        "- Only mention the registration window / pricing that is currently open or\n"
        "  still upcoming. If early-bird has ended, reference the current (e.g. standard)\n"
        "  tier instead, or omit pricing rather than advertising an expired deal.\n"
        "- Do not invent dates. If unsure whether a date is still valid, omit it.\n"
        "- DURATION CONSISTENCY: if the event date is a range (e.g. \"August 11-12, 2026\"),\n"
        "  never describe it as \"a full day\" or \"a day of\" anywhere in the copy — say\n"
        "  \"two days\" / \"August 11-12\" consistently. Derive the duration word choice\n"
        "  (day / two days / three days) from the actual date range given above, and use\n"
        "  the same number of days everywhere in the email — never contradict the dates."
    )

    # Upload hero / logo / sponsor images to HubSpot CDN for reliable rendering
    from hubspot_tools import upload_image_to_hubspot as _upload_img
    _log.info(f"[GEN_EMAIL] hero={hero_img!r} logo={logo_img!r} source_ref={source_email_id!r}")
    if hero_img:
        hero_img = _upload_img(hero_img) or hero_img
    if logo_img:
        logo_img = _upload_img(logo_img) or logo_img
    banner_url = hero_img

    # Upload sponsor logos to HubSpot CDN.
    # Only keep sponsors whose logo successfully uploaded — text-only sponsors are excluded.
    uploaded_sponsors = []
    for sp in sponsors:
        if isinstance(sp, dict):
            raw_logo = sp.get("logo_url", "")
            if not raw_logo:
                continue  # no logo URL at all — skip
            cdn_logo = _upload_img(raw_logo) or raw_logo
            if cdn_logo:
                uploaded_sponsors.append({"name": sp.get("name", ""), "logo_url": cdn_logo})
    sponsors = uploaded_sponsors
    _log.info(f"[GEN_EMAIL] sponsors with logos: {len(sponsors)} (text-only sponsors excluded)")

    # Build supplementary context lines
    reg_lines = []
    if reg.get("ticket_types"):
        reg_lines.append(f"Ticket info: {'; '.join(reg['ticket_types'][:2])}")
    if reg.get("deadlines"):
        reg_lines.append(f"Deadline: {reg['deadlines'][0]}")
    if reg.get("url"):
        reg_lines.append(f"Register at: {reg['url']}")
    reg_info = "\n".join(reg_lines)

    # Named action links — each CTA must point to the RIGHT sub-page, not the main URL.
    links = event_details.get("links", {}) or {}
    _link_labels = {
        "register": "Registration page",
        "sponsor":  "Sponsorship page",
        "cfp":      "Call for Proposals / submit a talk or poster",
        "schedule": "Schedule / agenda page",
        "venue":    "Venue & travel page",
    }
    _link_lines = [f"  • {_link_labels[k]}: {links[k]}" for k in _link_labels if links.get(k)]
    links_block = (
        "━━━ EVENT LINKS — point each CTA at the CORRECT page ━━━━━━━━━━━━━━━━━━━━━\n"
        + ("\n".join(_link_lines) if _link_lines else "  (only the main event page is available)")
        + f"\n  • Main event page: {url}\n\n"
        "RULE — set each button's url to the link matching its purpose:\n"
        "  Register / Save the Date / Attend  → Registration page (else main page)\n"
        "  Become a Sponsor / Sponsorship     → Sponsorship page\n"
        "  Submit a Proposal / Talk / Poster / CFP → Call for Proposals link\n"
        "  View Schedule / Agenda             → Schedule page\n"
        "  Venue / Travel / Hotel             → Venue & travel page\n"
        "  Fall back to the main event page ONLY when the specific link is missing.\n"
        "  Do NOT point every button at the same URL when specific links exist."
    )

    speakers_str = "\n".join(f"  • {s}" for s in speakers) if speakers else "  (to be announced)"

    def _sponsor_line(s) -> str:
        if isinstance(s, dict):
            name = s.get("name", "")
            logo = s.get("logo_url", "")
            return f"  • {name}" + (f"  [logo: {logo}]" if logo else "")
        return f"  • {s}"

    sponsors_str = "\n".join(_sponsor_line(s) for s in sponsors) if sponsors else "  (not listed on event page)"
    topics_str   = ", ".join(topics[:4]) if topics else "Open Source, Cloud Native, Linux"

    # HubSpot personalization tokens
    hs_firstname = "{{ contact.firstname }}"
    hs_company   = "{{ contact.company }}"

    # ── Read the TOP reference emails (up to 3) and choose the best ───────────
    # We read the ACTUAL CONTENT of each candidate — not just names — then use the
    # richest one as the structural template and ALL of them to learn the house
    # style/tone. reference_ids is ranked (best first); fall back to source_email_id.
    ref_block   = ""
    style_block = ""
    ref_name    = ""
    ref         = {}   # primary reference (kept in scope for button-color derivation)

    _ref_ids = [r for r in (reference_ids or []) if r][:3] or ([source_email_id] if source_email_id else [])
    refs_read: list = []
    if _ref_ids:
        try:
            import hubspot_tools as _ht
            for _rid in _ref_ids:
                try:
                    r = _ht.get_email_content_text(_rid)
                    if r.get("success") and (r.get("sections") or r.get("body_html")):
                        refs_read.append(r)
                except Exception as _e:
                    _log.warning(f"[GEN_EMAIL] reference {_rid} read failed: {_e}")
        except Exception as exc:
            _log.warning(f"[GEN_EMAIL] reference read exception: {exc}")

    if refs_read:
        # Primary = the richest reference (most rich_text blocks) → best template.
        def _richness(r: dict) -> int:
            return sum(1 for s in (r.get("sections") or []) if s.get("type") == "rich_text")
        ref = max(refs_read, key=_richness)
        ref_sections  = ref.get("sections", [])
        ref_body_html = ref.get("body_html", "")
        ref_name = ref.get("email_name", "")
        ref_subj = ref.get("subject", "")
        ref_prev = ref.get("preview_text", "")

        layout_lines = []
        for i, comp in enumerate(ref_sections):
            ctype = comp.get("type", "")
            if ctype == "image":
                layout_lines.append(f"  [{i+1}] IMAGE — hero banner (full-width event graphic)")
            elif ctype == "image_row":
                imgs = comp.get("images", [])
                alts = ", ".join(im.get("alt", "?") for im in imgs)
                layout_lines.append(f"  [{i+1}] IMAGE ROW ({len(imgs)} columns) — sponsor logos: {alts}")
            elif ctype == "rich_text":
                preview = _re.sub(r"<[^>]+>", "", comp.get("html", ""))[:80].strip()
                layout_lines.append(f"  [{i+1}] RICH TEXT — \"{preview}…\"")
            elif ctype == "button":
                layout_lines.append(
                    f"  [{i+1}] BUTTON — \"{comp.get('text','')}\" "
                    f"bg={comp.get('background_color','#04c0da')}"
                )
            elif ctype == "divider":
                layout_lines.append(f"  [{i+1}] DIVIDER — {comp.get('style','solid')} {comp.get('height',1)}px")
            elif ctype == "social_icons":
                layout_lines.append(f"  [{i+1}] SOCIAL ICONS — {comp.get('networks', [])}")

        ref_block = (
            f"━━━ PRIMARY REFERENCE EMAIL (mirror THIS structure) ━━━━━━━━━━━━━━━━━━━━━\n"
            f"Name    : {ref_name}\n"
            f"Subject : {ref_subj}\n"
            f"Preview : {ref_prev}\n\n"
            f"COMPONENT LAYOUT (replicate this exact sequence):\n"
            f"{chr(10).join(layout_lines)}\n\n"
            f"RICH TEXT HTML (actual HTML from each text block, in order):\n"
            f"{ref_body_html}\n"
        )

        # Style/tone corpus — text from ALL read references (incl. primary) so Claude
        # learns the brand's voice, greeting/sign-off, phrasing, emoji & CTA style.
        style_parts = []
        for k, r in enumerate(refs_read, 1):
            txt = _re.sub(r"<[^>]+>", " ", r.get("body_html", "") or "")
            txt = _re.sub(r"\s+", " ", txt).strip()[:900]
            if txt:
                style_parts.append(
                    f"[Ref {k}] {r.get('email_name','')}\n"
                    f"  Subject: {r.get('subject','')}\n"
                    f"  Body voice sample: {txt}"
                )
        if style_parts:
            style_block = (
                "━━━ STYLE & TONE REFERENCES (learn the house voice from ALL of these) ━━━\n"
                "These are real past emails for this brand. Match their tone, voice, greeting\n"
                "and sign-off style, sentence rhythm, emoji usage, and CTA phrasing. Do NOT\n"
                "copy their event-specific facts (names, dates, prices) — only the STYLE.\n\n"
                + "\n\n".join(style_parts) + "\n"
            )

        _log.info(
            f"[GEN_EMAIL] read {len(refs_read)} reference(s); primary={ref_name!r} "
            f"(richness={_richness(ref)}); style corpus from {len(style_parts)} email(s)"
        )
    else:
        _log.warning("[GEN_EMAIL] no readable reference emails — will use stage template")

    # ── Fallback to official marketing stage template ──────────────────────────
    template_block = ""
    if not ref_block:
        from email_templates import get_template
        tmpl = get_template(stage_name) or get_template("Event Announcement")
        template_block = (
            f"━━━ STAGE TEMPLATE (use when no reference email is available) ━━━━━━━━━━━━\n"
            f"Subject   : {tmpl['subject']}\n"
            f"Preheader : {tmpl['preheader']}\n\n"
            f"Body:\n{tmpl['body']}\n"
        )
        _log.info(f"[GEN_EMAIL] using fallback template for stage={stage_name!r}")

    # ── Build the prompt ───────────────────────────────────────────────────────
    # Default teal; overridden below when a reference email supplies its own button color.
    ref_btn_color = "#04c0da"
    if ref_block:
        for comp in (ref.get("sections") or []):
            if comp.get("type") == "button" and comp.get("background_color"):
                ref_btn_color = comp["background_color"]
                break

        task_instructions = f"""\
━━━ YOUR TASK ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
You are given a COMPONENT LAYOUT and RICH TEXT HTML from a real previously sent
email. Build a new email for the event below that follows the same design exactly.

═══ COMPONENT-BY-COMPONENT RULES ═══════════════════════════════════════════════

For each component in the COMPONENT LAYOUT above, output the matching HTML:

▸ IMAGE (hero banner)
  — The system injects the hero banner automatically. Skip this in your output.

▸ RICH TEXT blocks
  — Copy the inline CSS from the reference HTML exactly (font-size, line-height,
    color, background-color, text-align, font-weight).
  — Keep the same heading style: if the reference uses <p> with inline bold+size,
    use <p>; if it uses <h2>, use <h2>. Do NOT switch tag types.
  — Keep emoji prefixes on section headings (💡 🎟️ 🤝 etc.) — pick appropriate
    emoji for each section based on the stage context.
  — Replace all event-specific text (name, date, location, URL, topics, speakers,
    sponsors) with the new event's details.
  — Keep body text font-size and color identical to the reference.

▸ BUTTON
  — For every CTA, output a SEPARATE button section object:
    {{"type": "button", "text": "REGISTER NOW >>", "url": "https://...", "color": "{ref_btn_color}"}}
  — Do NOT embed button HTML inside a rich_text section.
  — Button text must match the stage CTA: "{cta_label}"
  — If reference has multiple CTAs (one per section), output the same number of button sections.

▸ DIVIDER
  — Between major content sections, end the rich_text html with:
    <hr style="border:none;border-top:1px solid #000000;margin:20px 0;">

▸ IMAGE ROW (sponsor logos)
  — The system adds sponsor images automatically as native HubSpot image modules.
  — Do NOT include sponsor images or logos in any section.
  — Do NOT include sponsor names in the HTML sections either — the system handles them.
  — Do NOT include a "Thank You to Our Sponsors!" heading or any sponsor section header —
    the system injects this heading automatically before the sponsor logos.

▸ GREETING SPACING
  — If the greeting line uses a name/firstname token (e.g. "Hi {hs_firstname},"),
    put it in its own <p> tag with margin-bottom (e.g. margin:0 0 12px;) — never
    run the greeting and the next sentence together in the same <p> or joined by <br>.

▸ NO SIGN-OFF
  — Do NOT include a closing sign-off line such as "Regards,", "Best,", "Sincerely,",
    "The Linux Foundation", or any similar valediction anywhere in the body. If the
    reference email's rich-text HTML contains one (often a leftover artifact from an
    earlier cloned/reused email), drop it — do not copy it into the new email.

▸ STRICT SECTION ORDER — output section objects in this exact sequence:
  1. Greeting / intro paragraph  (rich_text)
  2. Event highlights / main body  (rich_text)
  3. Speakers section if speakers available  (rich_text)
  4. Topics / tracks if available  (rich_text)
  5. CTA button  (button section)
  6. Additional CTAs if reference had multiple  (button sections)
  Sponsors are added by the system after your last section — do NOT output them.

▸ SOCIAL ICONS / FOOTER / BANNER
  — The system injects banner, footer, social icons automatically. Skip in your output.
  — Do NOT include: "This email was sent by", address, "Subscription Center", "Unsubscribe",
    "{{ unsubscribe_link }}", or any footer-related text — the system adds these.

═══ STAGE & CONTENT RULES ═══════════════════════════════════════════════════════
Stage: {stage_name} ({funnel})
Primary CTA: "{cta_label}"
- Tailor headlines, urgency wording, and section focus to match this stage.
- CFP stage → focus on speaking topics, deadline, submission link.
- Registration stage → focus on early bird pricing, date, venue.
- Announcement stage → focus on event overview, why attend, save the date.

{("MARKETING STRATEGY FOR THIS STAGE (use as messaging direction):\n  " + marketing_strategy) if marketing_strategy else ""}

{("CONTENT IDEAS FOR THIS STAGE (draw from these for section headlines & copy):\n" + chr(10).join(f"  • {idea}" for idea in content_ideas[:6])) if content_ideas else ""}

DESIGN RULE: Copy the EXACT design, layout, and component structure from the reference email
above. Only the copy/messaging/content changes — never the visual structure or styling.

Speaker list: include ALL confirmed speakers (never say "and more").
Sponsor list: include ALL sponsors (never say "and more" — but do NOT render them in sections).

HubSpot personalization tokens (exact syntax — spaces and dots matter):
  First name : {hs_firstname}
  Company    : {hs_company}

═══ OUTPUT FORMAT ════════════════════════════════════════════════════════════════
- Output sections in the JSON sections array — NOT as a single HTML block.
- Each rich_text "html" value: inline HTML paragraphs/lists only. No outer <div> wrapper.
  Use inline CSS (font-size, line-height, color, text-align, etc.) — no <style> tags.
- Each CTA button: a separate button section object — NOT embedded HTML in rich_text.
- Do NOT include: <html>, <head>, <body>, outer <div> wrapper, banner image,
  sponsor images/names, social icons, footer, or unsubscribe content.
- Bullet lists: <ul>/<li> tags — never the • character."""
    else:
        task_instructions = f"""\
━━━ YOUR TASK ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Replace every placeholder ([Event Name], [City], [Dates], [LINK], etc.) with
the real event details above and produce an ordered sections array.

1. Stage: {stage_name} ({funnel}) — CTA: "{cta_label}"
{("   Marketing strategy: " + marketing_strategy) if marketing_strategy else ""}
{("   Content ideas (draw from these for section copy):" + chr(10) + chr(10).join("   • " + idea for idea in content_ideas[:5])) if content_ideas else ""}

2. Include ALL speakers listed (with names — do not say "and more").
3. Do NOT include sponsor images/names — the system adds them as native modules.

4. HubSpot personalization tokens (EXACT syntax):
   - First name : {hs_firstname}
   - Company    : {hs_company}
   - Greeting spacing: if the greeting uses a name/firstname token (e.g. "Hi {hs_firstname},"),
     put it in its own <p> tag with margin-bottom (e.g. margin:0 0 12px;) — never run the
     greeting and the next sentence together in the same <p> or joined by <br>.

4b. NO SIGN-OFF: do NOT include a closing sign-off line such as "Regards,", "Best,",
    "Sincerely," or "The Linux Foundation" anywhere in the body — drop any such line
    even if it appears in reference/cloned content.

5. Output sections array — NOT a single HTML block:
   - rich_text sections: inline HTML only (no outer div wrapper, no style tags)
   - button sections: {{"type":"button","text":"...","url":"...","color":"#04c0da"}}
   - Do NOT include banner, sponsor images, footer, or unsubscribe content.
   Bullet lists as <ul>/<li>. Inline CSS only."""

    _stage_num_label = f"Stage {stage_info.get('stage_number')} — " if stage_info.get("stage_number") else ""
    prompt = f"""You are a senior email marketer for Linux Foundation open source events.

{ref_block or template_block}
{style_block}
━━━ NEW EVENT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Event Name  : {event_name}
Date        : {dates_display}
Location    : {location}
Event URL   : {url}
Description : {description}
Stage       : {_stage_num_label}{stage_name} ({funnel})

Confirmed Speakers:
{speakers_str}

Sponsors / Partners:
{sponsors_str}

Topics      : {topics_str}
{reg_info}

{links_block}

{date_rule}

{task_instructions}

Return ONLY a JSON object — no markdown fences, no text before or after:
{{"subject": "...", "preview_text": "...", "sections": [...]}}

subject: email subject line (max 60 chars, matches {stage_name} urgency)
preview_text: preheader text (max 90 chars)
sections: ordered array of content blocks. The system automatically adds the hero
  banner image, sponsor images/names, social icons footer, and unsubscribe footer —
  do NOT include those.

  Each block must be one of:
    Rich text: {{"type": "rich_text", "html": "<p style='...'>...</p>"}}
    CTA button: {{"type": "button", "text": "REGISTER NOW >>", "url": "https://...", "color": "#46b6b3"}}

  CRITICAL:
    - Do NOT embed buttons as HTML in rich_text blocks — separate button objects only.
    - Do NOT include sponsor images, sponsor names, banner, footer, or social icons.
    - rich_text "html" must NOT have an outer <div> wrapper — just the inner content.
{("" if not change_request else f"{chr(10)}━━━ CHANGE REQUEST ━━━{chr(10)}{change_request}{chr(10)}")}"""

    raw = _claude_text(prompt, max_tokens=6000, timeout=240)

    # Strip markdown fences
    raw = _re.sub(r'^```(?:json)?\s*', '', raw.strip())
    raw = _re.sub(r'\s*```\s*$', '', raw)

    # Extract outermost JSON object
    depth, start = 0, -1
    for i, ch in enumerate(raw):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start != -1:
                try:
                    data = json.loads(raw[start:i + 1])
                    sections_list = data.get("sections") or []
                    # Backwards compat: if Claude returned "html" instead of "sections"
                    if not sections_list and data.get("html"):
                        sections_list = [{"type": "rich_text", "html": str(data["html"])}]
                    sections_list = _drop_system_sections(sections_list, sponsors)
                    body_html    = _sections_to_html(sections_list, ref_btn_color, sponsors)
                    preview_html = _build_email_preview(
                        banner_url, body_html, url, event_name
                    )
                    return {
                        "subject":      str(data.get("subject", "")),
                        "preview_text": str(data.get("preview_text", "")),
                        "html":         preview_html,   # full HTML for UI iframe
                        "body_html":    body_html,      # flat HTML fallback
                        "sections":     sections_list,  # structured sections for native modules
                        "sponsors":     sponsors,       # CDN-uploaded sponsors
                        "banner_url":   banner_url,     # uploaded HubSpot CDN URL (or "")
                    }
                except json.JSONDecodeError:
                    break

    raise ValueError(f"Claude did not return valid JSON. Raw[:400]: {raw[:400]}")


def ai_select_source_email(
    event_name: str,
    event_short_name: str,
    location: str,
    candidates: list,
    url: str = "",
    max_attempts: int = 5,
) -> dict | None:
    """
    Ask Claude to pick the best source email to clone from a pre-filtered candidate list.

    Candidates are already strictly locale-filtered by the caller (main.py) —
    every email in `candidates` matches the new event's city/region/country.
    The caller never widens the pool to other locales, so an empty `candidates`
    list means "no same-locale history" and this function returns None immediately.

    Each attempt:
      1. Show Claude the email list + full event context (name, short name, location, URL).
      2. Claude follows a 3-tier priority rubric and replies structured:
           SELECT: <id>  /  CONFIDENT: YES or NO  /  REASON: ...
      3. CONFIDENT YES + valid ID → done.
      4. CONFIDENT NO or bad ID  → inject feedback and retry up to max_attempts.
    Returns None after all attempts (caller falls back to keyword scoring).
    """
    if not candidates:
        return None

    from datetime import datetime as _dt

    def _fmt_pub(ts) -> str:
        try:
            return _dt.fromtimestamp(int(ts) / 1000).strftime("%Y-%m-%d")
        except Exception:
            return str(ts)

    lines = [
        f"  ID: {e['id']}  |  {e.get('name', '(no name)')}  |  sent: {_fmt_pub(e.get('publishDate', 0))}"
        for e in candidates
    ]
    email_list = "\n".join(lines)
    url_line = f"Event URL  : {url}\n" if url else ""

    rejection_hint = ""

    for attempt in range(1, max_attempts + 1):
        prompt = (
            "You are a marketing operations specialist selecting the best HubSpot email\n"
            "template to clone for a new event campaign.\n\n"
            "━━━ NEW EVENT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Event Name : {event_name}\n"
            f"Short Name : {event_short_name}\n"
            f"Location   : {location}\n"
            f"{url_line}"
            "\n"
            "━━━ CANDIDATE EMAILS (sent emails for this brand, newest first) ━━━━━━━━━━━\n"
            f"{email_list}\n"
            "\n"
            f"{rejection_hint}"
            "━━━ SELECTION RULES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "PRIORITY 1 — EXACT MATCH (preferred):\n"
            f"  Same event series + same city/region → look for '{location.split(',')[0]}' in the name.\n"
            "\n"
            "PRIORITY 2 — SERIES MATCH:\n"
            f"  Same event series, any location → look for '{event_short_name}' or key words\n"
            f"  from '{event_name}' in the name.\n"
            "\n"
            "PRIORITY 3 — BRAND MATCH (last resort):\n"
            "  Same brand, most recently sent — only if no series match exists.\n"
            "\n"
            "CRITICAL RULES:\n"
            "  • NEVER pick an email from a different region when a location-specific\n"
            f"    email exists (e.g. do NOT pick 'North America' if '{location.split(',')[0]}' is available).\n"
            "  • Prefer the most recent edition of the matched series.\n"
            "  • A 'Last Chance' or 'Save the Date' email for the correct event is\n"
            "    better than an 'Invite' for the wrong location.\n"
            "  • Match on event series keywords: ignore generic words like 'summit',\n"
            "    'conference', 'register', 'join', 'meet'.\n"
            "\n"
            "━━━ YOUR ANSWER ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Reply in EXACTLY this format (3 lines, nothing else):\n"
            "SELECT: <email_id>\n"
            "CONFIDENT: YES or NO\n"
            "REASON: <one sentence explaining priority tier used and why>"
        )

        try:
            raw = _claude_text(prompt, max_tokens=150)
        except Exception as exc:
            _log.warning(f"[AI SELECT] attempt {attempt}: Claude call failed: {exc}")
            continue

        _log.info(f"[AI SELECT] attempt {attempt} response: {raw!r}")

        sel_id, confident = None, False
        for line in raw.splitlines():
            ls = line.strip()
            if ls.upper().startswith("SELECT:"):
                sel_id = ls.split(":", 1)[1].strip().split()[0]
            if ls.upper().startswith("CONFIDENT:"):
                confident = "YES" in ls.upper()

        if not sel_id:
            _log.warning(f"[AI SELECT] attempt {attempt}: no SELECT: line found")
            rejection_hint = (
                "⚠️  Your previous response did not contain a SELECT: line.\n"
                "Follow the 3-line format exactly.\n\n"
            )
            continue

        matched = next((e for e in candidates if str(e.get("id")) == sel_id), None)
        if not matched:
            _log.warning(f"[AI SELECT] attempt {attempt}: ID {sel_id} not in candidate list")
            rejection_hint = (
                f"⚠️  ID {sel_id} does not appear in the candidate list above.\n"
                "Choose an ID exactly as shown.\n\n"
            )
            continue

        if confident:
            _log.info(f"[AI SELECT] ✓ attempt {attempt}: '{matched.get('name')}' (id={sel_id})")
            return matched

        _log.info(f"[AI SELECT] attempt {attempt}: not confident about '{matched.get('name')}', retrying")
        rejection_hint = (
            f"⚠️  Attempt {attempt}: you selected '{matched.get('name')}' but marked CONFIDENT: NO.\n"
            f"Re-examine the list focusing on '{location.split(',')[0]}' and '{event_short_name}'.\n\n"
        )

    _log.warning(f"[AI SELECT] all {max_attempts} attempts exhausted — returning None")
    return None


# ── Public interface — called by main.py ──────────────────────────────────────

def run_turn(messages: list, user_message: str) -> tuple[str, list]:
    """One agentic turn through the deterministic gateway (same on every backend)."""
    system = SYSTEM_PROMPT.format(date=datetime.now().strftime("%Y-%m-%d"))
    convo = messages + [{"role": "user", "content": user_message}]
    return llm_gateway.run_agent(
        convo,
        system=system,
        tools=TOOLS,
        execute_tool=lambda name, inp: _execute_tool(name, inp),
        max_tokens=4096,
        max_steps=8,
    )


def plan_turn(session, url: str) -> tuple[str, list]:
    prompt = (
        f"The user wants to stage an email for this event URL:\n{url}\n\n"
        "CRITICAL — follow this order STRICTLY:\n"
        "  STEP 1: Call fetch_url to extract event_name, brand_name, location, event_dates.\n"
        "  STEP 2: Call search_emails_for_event(brand_name, event_name, location).\n"
        "          If event_match=False, also call lookup_brand_history as fallback.\n"
        "  STEP 3: Detect the marketing stage from event details.\n"
        "  STEP 4: Map stage to campaign_type, then call get_recommended_template(campaign_type).\n"
        "  STEP 5: ONLY AFTER steps 1-4 are done, write the full plan including template recommendation.\n\n"
        "BEST-PRACTICE TEMPLATE SECTION (add to plan after Stage & Content Overview):\n"
        "  After detecting stage in STEP 3, call get_recommended_template() to get:\n"
        "    - Template name (e.g., 'B2B_Event_Announcement')\n"
        "    - Quality rating (1-5 stars, shown as ★★★★★)\n"
        "    - Expected open rate and CTR from ArgoCon data\n"
        "    - Marketing strategy (e.g., 'Build excitement + relationship focus + multiple CTAs')\n"
        "  \n"
        "  Include a new section in the plan:\n"
        "    ### VARIANT B (Best-Practice Template) — Auto-Generated\n"
        "    Template: [Template Name] (★★★★★)\n"
        "    Expected Performance: [XX]% open rate, [XX]% CTR\n"
        "    Strategy: [Strategy from template]\n"
        "    Source: ArgoCon + KeycloakCon Japan 2026\n"
        "    \n"
        "    This variant will be automatically generated after you provide content for Variant A.\n"
        "    You can review both before sending.\n\n"
        "⚠️  DO NOT write any plan content before completing STEP 1 and STEP 2.\n"
        "⚠️  DO NOT say 'the plan above', 'as shown above', or 'presented above'.\n"
        "⚠️  Your FINAL message must contain the COMPLETE plan written from scratch.\n\n"
        "Your final response MUST contain the full plan in this EXACT format "
        "(all four sections — Stage & Content Overview FIRST, then Settings, then Audience):\n\n"
        "---\n"
        "## Email Staging Plan — [Event Name]\n\n"
        "One sentence: what event, what type of email, which stage.\n\n"
        "### Stage & Content Overview\n\n"
        "| Field | Value |\n"
        "|---|---|\n"
        "| **Current Stage** | [stage name] ([funnel] — [N] days to event) |\n"
        "| **Stage Goal** | [what this email is trying to achieve] |\n"
        "| **Email Type** | [Invite / Last Chance / Reminder / Newsletter / etc.] |\n"
        "| **CTA** | [call-to-action label] |\n"
        "| **Event Date** | [event date] |\n"
        "| **Content Reference** | [name of previous email used as style reference, or 'Stage template'] |\n\n"
        "**What will be included in the generated email:**\n"
        "- **Speakers**: [list ALL confirmed speaker names, or 'To be announced']\n"
        "- **Sponsors / Partners**: [list ALL confirmed sponsor names, or 'None found']\n"
        "- **Topics / Tracks**: [list]\n"
        "- **Email Sections**: [intro paragraph → [stage-specific content] → speaker highlights → "
        "registration CTA → closing]\n\n"
        "### Settings\n\n"
        "| Field | Value |\n"
        "|---|---|\n"
        "| **Email Name** | `26QN - Brand - Event - Suffix` |\n"
        "| **From Name** | (from brand history) |\n"
        "| **From Address** | (from brand history) |\n"
        "| **Subject Line** | *(auto-generated — shown below the plan)* |\n"
        "| **Preview Text** | *(auto-generated — shown below the plan)* |\n\n"
        "### Audience\n\n"
        "| | |\n"
        "|---|---|\n"
        "| **Send List** | (list name and contact count from brand history) |\n"
        "| **Suppression Lists** | (all suppression list IDs/names from brand history) |\n\n"
        "### Messaging Variant (Optional)\n\n"
        "We have multiple messaging strategies available for this stage. Each variant emphasizes\n"
        "different selling points (value vs urgency vs social proof). You can accept the recommended\n"
        "one or choose a different approach:\n\n"
        "**Available variants:**\n"
        "[The agent will call get_variant_strategies(stage) to show available options here]\n\n"
        "- **Recommended**: [variant_id] — [reason]\n"
        "- To choose a different variant, say: \"Use variant [variant_id]\" in your response.\n"
        "- If you're happy with the recommended variant, just proceed to the next step.\n\n"
        "---\n\n"
        "When ready, say \"Approve\" or \"Let's go\" to proceed to the next step.\n"
        "Optional: Say \"Use variant [variant_id]\" to select a different messaging approach.\n\n"
        "Do NOT ask for subject line, preview text, send date, or any other inputs.\n"
        "Do NOT mention cloning, source emails, or templates anywhere.\n"
        "Do NOT say 'the plan above' or 'as shown above' — write everything in this single response."
    )
    return run_turn(session.messages, prompt)


def clone_turn(session, subject=None, preview_text=None, send_list_id=None) -> tuple[str, list]:
    global _session_email_id, _session_email_ids_allowed
    _session_email_id = None
    _session_email_ids_allowed.clear()  # Reset allowed emails for new session

    brand = session.meta.get("brand_history") or extract_brand_history_from_messages(session.messages)

    # search_emails_for_event returns matched_email_id; lookup_brand_history returns last_email_id
    source_id = (brand or {}).get("last_email_id") or (brand or {}).get("matched_email_id")
    if not source_id:
        raise RuntimeError(
            "No source email found for cloning. Please re-run the plan step so the system "
            "can locate a previous email for this brand/event."
        )
    from_name   = brand.get("from_name", "")
    from_addr   = brand.get("from_address", "")
    suppression = brand.get("suppression_list_ids", [])
    email_type  = brand.get("email_type", "BATCH_EMAIL")

    # email_name is set deterministically during the plan step. Last-resort fallback
    # builds a sensible name from event context (never the bare "Brand - Email").
    email_name = session.meta.get("email_name")
    if not email_name:
        _ud     = session.meta.get("url_data", {}) or {}
        _si     = session.meta.get("stage_info", {}) or {}
        _code   = session.meta.get("short_brand_name") or brand.get("brand_name", "")
        _evt    = _ud.get("event_name", "")
        _suffix = _si.get("email_type", "") or "Invite"
        _yyq    = ""
        import re as __re
        for _ds in (_ud.get("event_dates") or []):
            _m = __re.match(r"(\d{4})-(\d{2})-(\d{2})", str(_ds))
            if _m:
                _yyq = f"{int(_m.group(1)) % 100:02d}Q{(int(_m.group(2)) - 1) // 3 + 1}"
                break
        _parts = [p for p in (_code, _evt, _suffix) if p]
        email_name = (f"{_yyq} - " if _yyq else "") + " - ".join(_parts) if _parts else (_evt or "Email Campaign")

    _log.info(f"[CLONE] brand_history keys: {list((brand or {}).keys())}")
    _log.info(f"[CLONE] source_id={source_id!r} from_name={from_name!r} from_addr={from_addr!r}")
    _log.info(f"[CLONE] suppression={suppression!r}")
    _log.info(f"[CLONE] included_list_ids={brand.get('included_list_ids')!r}")

    # ── Variant selection ──
    stage_name = session.meta.get("stage_name", "")
    variant_id = extract_variant_id_from_messages(session.messages)

    if not variant_id and stage_name:
        # Use recommended variant if user didn't specify one
        variant_id, reason = _recommend_variant_strategy(stage_name)
        _log.info(f"[CLONE] Using recommended variant: {variant_id} — {reason}")

    if variant_id:
        session.meta["selected_variant_id"] = variant_id
        _log.info(f"[CLONE] Selected variant: {variant_id}")

    # ── Store source_email_id for Variant B creation in content_turn ──
    session.meta["source_email_id"] = source_id
    _log.info(f"[CLONE] Stored source_email_id: {source_id}")

    # ── Get and store best-practice template recommendation for Variant B ──
    if stage_name:
        campaign_type_map = {
            "Event Announcement": "announcement",
            "Registration Launch": "registration_launch",
            "CFP Launch": "registration_launch",
            "Schedule Announcement": "announcement",
            "Final Countdown": "registration_launch",
            "Speaker Confirmation": "speaker_conversion",
            "Sponsorship Outreach": "multi_event_deal",
        }
        campaign_type = campaign_type_map.get(stage_name, "announcement")
        template_rec = email_templates.recommend_best_practice_template(campaign_type)
        if template_rec:
            # Extract necessary fields for Variant B creation
            template_obj = template_rec.get("template", {})
            session.meta["recommended_template_for_variant_b"] = {
                "template_key": template_rec.get("key", ""),
                "quality_rating": template_obj.get("quality_rating", 0),
                "expected_open_rate": template_obj.get("key_metrics", {}).get("expected_open_rate", 0),
                "expected_ctr": template_obj.get("key_metrics", {}).get("expected_ctr", 0),
                "strategy": template_obj.get("template", {}).get("strategy", ""),
                "source": template_obj.get("source", ""),
            }
            _log.info(f"[CLONE] Stored template recommendation for Variant B: {session.meta['recommended_template_for_variant_b']['template_key']}")

    # Generate subject/preview from variant if not provided
    if not subject and not preview_text and stage_name and variant_id:
        url_data = session.meta.get("url_data", {}) or {}
        subject, preview_text = _get_variant_subject_preview(stage_name, variant_id, url_data)
        _log.info(f"[CLONE] Generated subject from variant: {subject[:60]!r}")

    # Fall back to auto-generated subject/preview from plan phase if user didn't provide them
    effective_subject      = subject      or session.meta.get("generated_subject", "")
    effective_preview_text = preview_text or session.meta.get("generated_preview", "")

    # Auto-detect send list — priority: user pick > built audience > brand history
    effective_send_list = send_list_id
    if not effective_send_list:
        audience_list_id = session.meta.get("audience_list_id")
        if audience_list_id:
            effective_send_list = str(audience_list_id)
            _log.info(f"[CLONE] using built audience list: {effective_send_list}")
    if not effective_send_list:
        included = (brand or {}).get("included_list_ids", [])
        if included:
            effective_send_list = str(included[0])

    _log.info(f"[CLONE] effective_send_list={effective_send_list!r} effective_subject={effective_subject[:40]!r}")

    # Step 1: Clone directly — bypass Claude to avoid hallucination in CLI mode
    clone_result = json.loads(
        _execute_tool("clone_email", {"source_email_id": source_id, "clone_name": email_name})
    )
    if "error" in clone_result:
        raise RuntimeError(f"Clone failed: {clone_result['error']}")

    new_email_id = clone_result["email_id"]
    draft_url    = clone_result.get("draft_url", "")

    # ── A/B TEST SETUP ───────────────────────────────────────────────────────
    # new_email_id (the fresh clone from Step 1) becomes Variant A — the AI-template
    # email — and is passed as contentId to create_ab_variation, so HubSpot marks it
    # the A/B "master". The email that API returns becomes Variant B and receives the
    # existing flow's content (today's stage-based, reference-email-driven Claude copy).
    variant_a_id = new_email_id
    url_data   = session.meta.get("url_data", {}) or {}
    stage_info = session.meta.get("stage_info", {}) or {}

    # Shared assets/context — both variants describe the same event, so Variant A
    # reuses Variant B's already-uploaded hero banner and sponsor logos rather than
    # re-uploading, and both need the same UTM params / event URL / sending-brand name.
    banner_url    = session.meta.get("banner_url", "")
    sponsors_list = session.meta.get("sponsors") or []
    event_url     = url_data.get("url", "")
    utm_params    = session.meta.get("utm_params")

    # Footer "This email was sent by: <org>" must match the actual sending brand
    # (e.g. "Cloud Native Computing Foundation" for CNCF), not be hardcoded to LF.
    _event_name_for_brand = url_data.get("event_name", "")
    _brand_entry = lookup_event_brand(_event_name_for_brand) if _event_name_for_brand else None
    sent_by_org = (_brand_entry or {}).get("brand_name", "")
    if sent_by_org == "The Linux Foundation":
        sent_by_org = "The Linux Foundation Events"

    variant_a_data = generate_ai_template_content(
        url_data, stage_info, banner_url=banner_url, sponsors=sponsors_list
    )
    variant_a_subject  = variant_a_data.get("subject") or effective_subject
    variant_a_preview  = variant_a_data.get("preview_text") or effective_preview_text
    variant_a_sections = variant_a_data.get("sections") or []
    variant_a_body_html = variant_a_data.get("body_html", "")

    # Step 2: Apply Variant A (AI Template) settings + content to the master clone.
    settings: dict = {
        "email_id":             variant_a_id,
        "from_name":            from_name,
        "from_address":         from_addr,
        "email_type":           email_type,
    }
    if variant_a_subject: settings["subject"]      = variant_a_subject
    if variant_a_preview: settings["preview_text"] = variant_a_preview

    update_result = json.loads(
        _execute_tool("update_email_settings", settings, session_email_id=variant_a_id)
    )
    if "error" in update_result:
        _log.warning(f"Settings update partial error: {update_result['error']}")

    variant_a_applied = False
    if variant_a_sections or variant_a_body_html:
        try:
            va_result = hubspot_tools.update_email_content(
                variant_a_id,
                html_content=variant_a_body_html if not variant_a_sections else "",
                banner_url=banner_url,
                event_url=event_url,
                content_sections=variant_a_sections or None,
                sponsors=sponsors_list or None,
                utm_params=utm_params,
                sent_by_org=sent_by_org,
            )
            if "error" not in va_result:
                variant_a_applied = True
                _log.info(
                    f"[CLONE] Variant A (AI Template) content applied method={va_result.get('method')!r} "
                    f"body={len(variant_a_body_html):,} chars banner={'yes' if banner_url else 'no'}"
                )
            else:
                _log.warning(f"[CLONE] Variant A content apply failed: {va_result.get('error')}")
        except Exception as e:
            _log.warning(f"[CLONE] Variant A content apply exception: {e}")

    if variant_a_applied:
        try:
            val_a = hubspot_tools.validate_staged_email(
                variant_a_id,
                expect_banner=bool(banner_url),
                expect_sections=max(1, len([s for s in variant_a_sections if s.get("type") == "rich_text"])) if variant_a_sections else 1,
            )
            if not val_a.get("valid", False):
                _log.info(f"[CLONE] Variant A validation issues={val_a.get('issues')} — retrying content patch once")
                try:
                    hubspot_tools.update_email_content(
                        variant_a_id,
                        html_content=variant_a_body_html if not variant_a_sections else "",
                        banner_url=banner_url,
                        event_url=event_url,
                        content_sections=variant_a_sections or None,
                        sponsors=sponsors_list or None,
                        utm_params=utm_params,
                        sent_by_org=sent_by_org,
                    )
                except Exception as retry_exc:
                    _log.warning(f"[CLONE] Variant A retry patch exception: {retry_exc}")
        except Exception as val_exc:
            _log.warning(f"[CLONE] Variant A validation exception: {val_exc}")

    # Step 3: Create Variant B as a true HubSpot A/B variation of Variant A.
    variant_b_id = ""
    try:
        ab_result = hubspot_tools.create_ab_variation(variant_a_id, f"{email_name} - Variant B (Existing Flow)")
        if ab_result.get("status") == "success":
            variant_b_id = ab_result.get("variant_id", "")
            _log.info(f"[CLONE] Created A/B variation: variant_b_id={variant_b_id}")
        else:
            _log.warning(f"[CLONE] A/B variation failed: {ab_result.get('error')}")
    except Exception as e:
        _log.warning(f"[CLONE] A/B variation exception: {e}")

    # The new variation inherits Variant A's subject/preview at creation time — restore
    # the existing-flow subject/preview below so the two variants stay distinguishable.
    # If the A/B variation couldn't be created, fall back to today's single-email
    # behavior: apply the existing-flow content directly onto the master instead.
    content_target_id = variant_b_id or variant_a_id

    # Step 4: Apply the existing flow's (Variant B) settings + content.
    # Prefer structured sections (native HubSpot modules) over flat body_html.
    # banner_url/sponsors_list/event_url/utm_params/sent_by_org were already computed
    # above (shared with Variant A); only content_sections/body_html are B-specific.
    content_applied    = False
    content_sections   = session.meta.get("sections") or []
    body_html          = session.meta.get("body_html") or session.meta.get("generated_html", "")

    if variant_b_id:
        b_settings: dict = {"email_id": variant_b_id}
        if effective_subject:      b_settings["subject"]      = effective_subject
        if effective_preview_text: b_settings["preview_text"] = effective_preview_text
        try:
            hubspot_tools.update_email_settings(**b_settings)
        except Exception as e:
            _log.warning(f"[CLONE] Variant B settings restore exception: {e}")

    if content_sections or body_html:
        try:
            content_result = hubspot_tools.update_email_content(
                content_target_id,
                html_content=body_html if not content_sections else "",
                banner_url=banner_url,
                event_url=event_url,
                content_sections=content_sections or None,
                sponsors=sponsors_list or None,
                utm_params=utm_params,
                sent_by_org=sent_by_org,
            )
            if "error" not in content_result:
                content_applied = True
                _log.info(
                    f"[CLONE] Variant B content applied method={content_result.get('method')!r} "
                    f"body={len(body_html):,} chars banner={'yes' if banner_url else 'no'}"
                )
            else:
                _log.warning(f"[CLONE] Content apply failed: {content_result.get('error')}")
        except Exception as e:
            _log.warning(f"[CLONE] Content apply exception: {e}")

    # Step 5: Validate the staged Variant B content before surfacing the URL.
    # Re-fetch from HubSpot and verify widgets, footer, and body sections are present.
    # On failure, retry the content patch once before giving up.
    validation_passed = False
    validation_issues: list = []
    if content_applied:
        try:
            val = hubspot_tools.validate_staged_email(
                content_target_id,
                expect_banner=bool(banner_url),
                expect_sections=max(1, len([s for s in content_sections if s.get("type") == "rich_text"])) if content_sections else 1,
            )
            validation_passed = val.get("valid", False)
            validation_issues = val.get("issues", [])
            _log.info(f"[CLONE] validation={'PASS' if validation_passed else 'FAIL'} "
                      f"summary={val.get('summary')} issues={validation_issues}")

            if not validation_passed:
                # Retry content patch once
                _log.info("[CLONE] Retrying content patch after validation failure…")
                try:
                    retry_result = hubspot_tools.update_email_content(
                        content_target_id,
                        html_content=body_html if not content_sections else "",
                        banner_url=banner_url,
                        event_url=event_url,
                        content_sections=content_sections or None,
                        sponsors=sponsors_list or None,
                        utm_params=utm_params,
                        sent_by_org=sent_by_org,
                    )
                    if "error" not in retry_result:
                        val2 = hubspot_tools.validate_staged_email(
                            content_target_id,
                            expect_banner=bool(banner_url),
                            expect_sections=max(1, len([s for s in content_sections if s.get("type") == "rich_text"])) if content_sections else 1,
                        )
                        validation_passed = val2.get("valid", False)
                        validation_issues = val2.get("issues", [])
                        _log.info(f"[CLONE] retry validation={'PASS' if validation_passed else 'FAIL'} "
                                  f"issues={validation_issues}")
                    else:
                        _log.warning(f"[CLONE] Retry patch failed: {retry_result.get('error')}")
                except Exception as retry_exc:
                    _log.warning(f"[CLONE] Retry patch exception: {retry_exc}")
        except Exception as val_exc:
            _log.warning(f"[CLONE] Validation exception: {val_exc}")
            validation_passed = False
            validation_issues = [str(val_exc)]
    else:
        validation_issues = ["Content was not applied to the email"]

    # Step 6: Apply send list LAST — after all content patches so nothing can
    # overwrite the `to` field. Applied to the master (Variant A) only — HubSpot's
    # A/B model keeps the `to`/test config on the master; the variation is content-only.
    # Uses set_email_send_list() which looks up the list's processingType and uses the
    # correct contactLists vs contactIlsLists sub-field; mixing them in a single PATCH
    # causes HubSpot to silently reject the entire `to` object.
    if effective_send_list:
        try:
            sls = hubspot_tools.set_email_send_list(variant_a_id, effective_send_list, suppression)
            _log.info(f"[CLONE] set_email_send_list → success={sls.get('success')} type={sls.get('list_type')}")
        except Exception as exc:
            _log.warning(f"[CLONE] set_email_send_list exception: {exc}")

    # Store flags + both variant ids/urls so main.py can gate the draft URL and
    # surface both variants to the frontend.
    variant_b_draft_url = f"https://app.hubspot.com/email/{HUBSPOT_PORTAL_ID}/edit/{variant_b_id}/settings" if variant_b_id else ""
    session.meta["content_applied"]     = content_applied
    session.meta["validation_passed"]   = validation_passed
    session.meta["validation_issues"]   = validation_issues
    session.meta["variant_a_email_id"]  = variant_a_id
    session.meta["variant_a_draft_url"] = draft_url
    session.meta["variant_b_email_id"]  = variant_b_id
    session.meta["variant_b_draft_url"] = variant_b_draft_url

    if validation_passed:
        text = (
            f"Email A/B test staged and validated successfully!\n\n"
            f"**Email Name:** {email_name}\n\n"
            f"**Variant A (AI Template):**\n"
            f"- Subject: {variant_a_subject}\n"
            f"- Draft URL: {draft_url}\n\n"
            f"**Variant B (Existing Flow):**\n"
            f"- Subject: {effective_subject}\n"
            f"- Preview Text: {effective_preview_text}\n"
            f"- Draft URL: {variant_b_draft_url or '(A/B variation could not be created — applied to Variant A instead)'}\n\n"
            "All content sections, banner, and footer were confirmed in HubSpot. "
            "Review both and schedule when ready."
        )
    elif content_applied:
        issues_str = "\n".join(f"- {i}" for i in validation_issues)
        text = (
            f"Email was created but validation found issues:\n\n"
            f"**Email Name:** {email_name}\n\n"
            f"Issues detected:\n{issues_str}\n\n"
            "A retry was attempted. Please check the email in HubSpot and verify the content manually."
        )
    else:
        text = (
            f"Email staged successfully!\n\n"
            f"**Email Name:** {email_name}\n\n"
            "Please provide the email content (Google Doc URL, raw HTML, or plain text) "
            "and I'll update the email body."
        )

    updated_messages = session.messages + [
        {"role": "user",      "content": "I approve the plan."},
        {"role": "assistant", "content": text},
    ]
    return text, updated_messages


# AI_STAGE_TEMPLATES key -> keycloak_argocon_templates.json stage key. The two libraries
# use slightly different stage names for the same funnel position; only the 5 forward-
# funnel stages have a real reference (there's no "Post-Event" campaign in that dataset).
_KEYCLOAK_ARGOCON_STAGE_MAP = {
    "CFP Launch":                          "CFP Launch",
    "Schedule Announcement":               "Schedule Announcement",
    "Registration Push / Pricing Deadline": "Registration / Pricing Push",
    "Discount Offer / VIP Access":         "Discount Offer",
    "Final Countdown":                     "Final Countdown",
}

_keycloak_argocon_templates_cache: dict | None = None


def _load_keycloak_argocon_templates() -> dict:
    """Load the real 'KeycloakCon + ArgoCon Japan' per-stage structure reference
    (subject/preview/CTA/paragraph patterns from actually-sent emails), cached after
    first read. Returns {} if the file is missing so callers degrade gracefully."""
    global _keycloak_argocon_templates_cache
    if _keycloak_argocon_templates_cache is None:
        try:
            _path = os.path.join(os.path.dirname(__file__), "keycloak_argocon_templates.json")
            with open(_path, "r", encoding="utf-8") as f:
                _keycloak_argocon_templates_cache = json.load(f)
        except Exception:
            _keycloak_argocon_templates_cache = {}
    return _keycloak_argocon_templates_cache


def generate_ai_template_content(
    url_data: dict,
    stage_info: dict,
    banner_url: str = "",
    sponsors: list = None,
) -> dict:  # noqa: C901
    """
    Generate Variant A (AI Template) content for the production A/B flow.

    Unlike generate_email_content() (Variant B, which reads THIS brand's own real
    reference emails), Variant A is driven by a fixed stage-template library
    (ai_email_templates.AI_STAGE_TEMPLATES) plus a structural style guide extracted
    from real past "KeycloakCon + ArgoCon Japan" emails (keycloak_argocon_templates.json)
    for the matching funnel stage — so each of the 5 AI-template stages mirrors the
    real cadence/CTA-density/tone sent for that same stage, without copying its facts.

    Generation goes through _claude_text() (the same CLI-fallback-aware helper used by
    generate_email_content()) instead of a direct Anthropic client, and reuses Variant
    B's already-uploaded banner_url/sponsors — both variants describe the same event, so
    there's no need to re-upload images here.

    Returns the same shape as generate_email_content(): {subject, preview_text, html,
    body_html, sections, sponsors, banner_url, template_key, stage_name, mode}. On
    failure, returns an empty-ish dict with "error" set — callers must tolerate this and
    fall back gracefully (Variant B / the clone must never be blocked by a Variant A
    generation failure).
    """
    import re as _re
    import logging as _logging
    _log = _logging.getLogger("email-staging")

    stage_name = (stage_info or {}).get("name", "Unknown")
    template_key = "CFP Launch"
    sponsors = sponsors or []

    try:
        event_name  = url_data.get("event_name", "Event")
        event_dates = url_data.get("event_dates", [])
        location    = url_data.get("location", "")
        description = (url_data.get("description") or "")[:400]
        url         = url_data.get("url", "")
        speakers    = url_data.get("speakers", [])
        topics      = url_data.get("topics", [])
        reg         = url_data.get("registration") or {}
        links       = url_data.get("links", {}) or {}

        cta_label          = stage_info.get("cta_label", "Register Now")
        event_date         = stage_info.get("event_date_str", "") or (event_dates[0] if event_dates else "")
        dates_display      = event_dates[0] if event_dates else event_date
        funnel             = stage_info.get("funnel", "")
        marketing_strategy = stage_info.get("marketing_strategy", "")
        content_ideas      = stage_info.get("content_ideas", [])

        template_key = ai_email_templates.map_funnel_stage_to_ai_template(stage_name)
        template = ai_email_templates.AI_STAGE_TEMPLATES.get(template_key) \
            or ai_email_templates.AI_STAGE_TEMPLATES["CFP Launch"]
        _log.info(f"[AI-TEMPLATE] funnel stage '{stage_name}' -> AI template '{template_key}'")

        # ── Structural style guide from real KeycloakCon+ArgoCon Japan emails ────
        ref_stage_key = _KEYCLOAK_ARGOCON_STAGE_MAP.get(template_key, "")
        ref_stage = (_load_keycloak_argocon_templates().get("stages") or {}).get(ref_stage_key, {})
        style_guide = ""
        if ref_stage:
            patterns = ref_stage.get("template_patterns", {})
            sample   = (ref_stage.get("emails") or [{}])[0].get("structure", {})
            sample_ctas  = "\n".join(f'  • "{c}"' for c in (sample.get("main_ctas") or [])[:5])
            sample_paras = "\n".join(f'  • "{t}"' for t in (sample.get("text_sections") or [])[:5])
            style_guide = (
                "━━━ STRUCTURE REFERENCE — real 'KeycloakCon + ArgoCon Japan' email for THIS stage ━━━\n"
                f"This is a REAL past email sent for the '{ref_stage_key}' stage of a co-located LF\n"
                "event campaign. Match its STRUCTURE, cadence, tone, and CTA density — do NOT copy\n"
                "its event-specific facts (names, dates, topics, prices); only mirror the shape.\n\n"
                f"Dominant tone        : {patterns.get('dominant_tone', sample.get('tone',''))}\n"
                f"Typical CTA count    : {patterns.get('avg_cta_count', sample.get('cta_count',''))}\n"
                f"Common urgency words : {', '.join(patterns.get('common_urgency_words') or [])}\n\n"
                f"Sample CTA phrasing (structure only — do not reuse facts):\n{sample_ctas}\n\n"
                f"Sample paragraph openings (structure/cadence only):\n{sample_paras}\n"
            )
        else:
            _log.info(f"[AI-TEMPLATE] no KeycloakCon+ArgoCon reference for template_key={template_key!r}")

        speakers_str = "\n".join(f"  • {s}" for s in speakers) if speakers else "  (to be announced)"
        topics_str   = ", ".join(topics[:4]) if topics else "Open Source, Cloud Native, Linux"
        sponsors_str = "\n".join(
            f"  • {s.get('name','') if isinstance(s, dict) else s}" for s in sponsors
        ) if sponsors else "  (not listed on event page)"

        reg_lines = []
        if reg.get("ticket_types"):
            reg_lines.append(f"Ticket info: {'; '.join(reg['ticket_types'][:2])}")
        if reg.get("deadlines"):
            reg_lines.append(f"Deadline: {reg['deadlines'][0]}")
        if reg.get("url"):
            reg_lines.append(f"Register at: {reg['url']}")
        reg_info = "\n".join(reg_lines)

        _link_labels = {
            "register": "Registration page",
            "sponsor":  "Sponsorship page",
            "cfp":      "Call for Proposals / submit a talk or poster",
            "schedule": "Schedule / agenda page",
            "venue":    "Venue & travel page",
        }
        _link_lines = [f"  • {_link_labels[k]}: {links[k]}" for k in _link_labels if links.get(k)]
        links_block = (
            "━━━ EVENT LINKS — point each CTA at the CORRECT page ━━━━━━━━━━━━━━━━━━━━━\n"
            + ("\n".join(_link_lines) if _link_lines else "  (only the main event page is available)")
            + f"\n  • Main event page: {url}\n\n"
            "RULE — set each button's url to the link matching its purpose; fall back to the\n"
            "main event page ONLY when the specific link is missing."
        )

        _today_str = datetime.now().strftime("%B %d, %Y")
        date_rule = (
            "━━━ CRITICAL — DATE AWARENESS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Today's date is {_today_str}. The event takes place on "
            f"{event_date or dates_display or 'the date above'}.\n"
            "- NEVER include a registration tier, early-bird price, or deadline that has\n"
            "  already passed relative to today. Do not invent dates — omit rather than guess."
        )

        hs_firstname = "{{ contact.firstname }}"
        hs_company   = "{{ contact.company }}"

        prompt = f"""You are a senior email marketer for Linux Foundation open source events,
writing Variant A of an A/B test: an "AI Template" email built from a fixed stage-template
library, structurally modeled on real past co-located-event campaign emails.

━━━ STAGE TEMPLATE ({template_key}) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Purpose        : {template.get('purpose','')}
Tone           : {template.get('tone','')}
Urgency (1-10) : {template.get('urgency_level','')}
CTA strategy   :
{chr(10).join('  • ' + c for c in template.get('cta_strategy', []))}

Content guidance:
{template.get('content_prompt','')}

{style_guide}
━━━ NEW EVENT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Event Name  : {event_name}
Date        : {dates_display}
Location    : {location}
Event URL   : {url}
Description : {description}
Stage       : {stage_name} ({funnel})

Confirmed Speakers:
{speakers_str}

Sponsors / Partners:
{sponsors_str}

Topics      : {topics_str}
{reg_info}

{links_block}

{date_rule}

{("MARKETING STRATEGY FOR THIS STAGE (use as messaging direction):\\n  " + marketing_strategy) if marketing_strategy else ""}

{("CONTENT IDEAS FOR THIS STAGE (draw from these for section headlines & copy):\\n" + chr(10).join(f"  • {idea}" for idea in content_ideas[:6])) if content_ideas else ""}

━━━ YOUR TASK ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Write a detailed, engaging, multi-paragraph email for the event above, following the
STAGE TEMPLATE's purpose/tone/CTA strategy and mirroring the STRUCTURE REFERENCE's
cadence (paragraph count, CTA density, urgency wording) — but ALL facts (name, dates,
speakers, sponsors, links) must be the NEW EVENT's real facts, never the reference's.

RULES:
- Never output a literal bracket placeholder like [EVENT_NAME] or [DATE] — always
  substitute the real value above. If a fact isn't available, write around it instead
  of leaving a placeholder in the output.
- Multiple distinct rich_text paragraphs (greeting, why-it-matters, details/topics,
  speakers if available) — never one flat paragraph dump.
- Real styled CTA buttons as separate button sections, matching the CTA strategy above
  (primary + at least one secondary CTA where the strategy lists one).
- Include ALL confirmed speakers by name (never "and more").
- Do NOT include sponsor images, sponsor names, or a sponsor heading in your sections —
  the system adds them automatically as native modules from the sponsors list.
- HubSpot personalization tokens (exact syntax): first name {hs_firstname}, company
  {hs_company}. If the greeting uses a name token, keep it in its own <p> with
  margin-bottom — never run it into the next sentence.
- No closing sign-off line ("Regards," / "Best," / "The Linux Foundation" etc.).
- Bullet lists: <ul>/<li> tags — never the • character.

═══ OUTPUT FORMAT ════════════════════════════════════════════════════════════════
Return ONLY a JSON object — no markdown fences, no text before or after:
{{"subject": "...", "preview_text": "...", "sections": [...]}}

subject: max 60 chars, matches {stage_name} urgency and the STAGE TEMPLATE's subject style
preview_text: preheader text, max 90 chars
sections: ordered array — the system automatically adds the hero banner image, sponsor
  images/names, social icons footer, and unsubscribe footer — do NOT include those.
  Each block must be one of:
    Rich text: {{"type": "rich_text", "html": "<p style='...'>...</p>"}}
    CTA button: {{"type": "button", "text": "...", "url": "https://...", "color": "#04c0da"}}
  Do NOT embed buttons as HTML inside rich_text blocks — separate button objects only.
  rich_text "html" must NOT have an outer <div> wrapper — just the inner content."""

        raw = _claude_text(prompt, max_tokens=4000, timeout=240)

        raw = _re.sub(r'^```(?:json)?\s*', '', raw.strip())
        raw = _re.sub(r'\s*```\s*$', '', raw)

        depth, start = 0, -1
        data = None
        for i, ch in enumerate(raw):
            if ch == '{':
                if depth == 0:
                    start = i
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0 and start != -1:
                    try:
                        data = json.loads(raw[start:i + 1])
                        break
                    except json.JSONDecodeError:
                        continue
        if data is None:
            raise ValueError(f"Claude did not return valid JSON. Raw[:400]: {raw[:400]}")

        sections_list = data.get("sections") or []
        if not sections_list and data.get("html"):
            sections_list = [{"type": "rich_text", "html": str(data["html"])}]
        sections_list = _drop_system_sections(sections_list, sponsors)
        body_html    = _sections_to_html(sections_list, "#04c0da", sponsors)
        preview_html = _build_email_preview(banner_url, body_html, url, event_name)

        return {
            "subject":      str(data.get("subject", "")),
            "preview_text": str(data.get("preview_text", "")),
            "html":         preview_html,
            "body_html":    body_html,
            "sections":     sections_list,
            "sponsors":     sponsors,
            "banner_url":   banner_url,
            "template_key": template_key,
            "stage_name":   stage_name,
            "mode":         "ai-generated",
        }
    except Exception as e:
        _log.error(f"[AI-TEMPLATE] generation failed: {e}", exc_info=True)
        return {
            "subject": "", "preview_text": "", "html": "", "body_html": "",
            "sections": [], "sponsors": sponsors, "banner_url": banner_url,
            "template_key": template_key, "stage_name": stage_name,
            "mode": "failed", "error": str(e),
        }


def content_turn(session, content_input: str) -> tuple[str, list]:
    """
    Content phase: always creates both variants, tied together as a real HubSpot A/B test.

      1. System generates Variant A content using AI (Claude) and applies it to the
         base email created in the Clone phase — this becomes the HubSpot A/B "master"
      2. System creates Variant B as a true HubSpot A/B variation of Variant A via the
         create-ab-variation API
      3. Agent processes user content → applies it to Variant B email (existing flow)
      4. System analyzes and optimizes Variant B (user-provided) content
      5. Both emails ready for A/B testing, linked natively in HubSpot
    """
    import logging as _logging
    _log = _logging.getLogger("email-staging")

    # Build context about the selected variant for content generation
    variant_id = session.meta.get("selected_variant_id")
    stage_name = session.meta.get("stage_name", "")
    variant_note = ""

    if variant_id and stage_name:
        variant = email_templates.get_template_variant(stage_name, variant_id)
        if variant:
            strategy = variant.get("strategy", "")
            template_body = variant.get("body", "")
            variant_note = (
                f"\n🎨 MESSAGING VARIANT SELECTED: {variant_id}\n"
                f"Strategy: {strategy}\n"
                f"\nThe email should follow this template structure and tone:\n"
                f"---\n{template_body[:500]}...\n---\n"
                f"\nUse the user-provided content, but maintain the messaging strategy and structure from the variant.\n"
            )

    # Get session data for both variants
    source_email_id = session.meta.get("source_email_id", "")
    email_name = session.meta.get("email_name", "Unnamed Campaign")
    url_data = session.meta.get("url_data", {})
    from_name = session.meta.get("from_name", "")
    from_address = session.meta.get("from_address", "")
    base_subject = session.meta.get("subject", "")

    # Step 1: Generate Variant A (AI Template) content and apply it to the base email.
    # This email must be the one passed as contentId to create_ab_variation, since HubSpot
    # marks whatever contentId we pass as the A/B "master" (state DRAFT_AB).
    _log.info("[CONTENT] Starting Variant A (AI Template) generation...")
    variant_a_id = session.meta.get("email_id", "")
    variant_a_data = {}
    detected_stage_name = "Unknown"
    ai_template_key = "CFP Launch"

    try:
        try:
            import generate_ai_content
            _log.info("[CONTENT] ✅ generate_ai_content module loaded")
        except ImportError as ie:
            _log.error(f"[CONTENT] ❌ Cannot import generate_ai_content: {ie}")
            raise

        event_data = {
            "event_name": url_data.get("event_name", "Event"),
            "location": url_data.get("location", "Location"),
            "dates": ", ".join(url_data.get("event_dates", [])) if url_data.get("event_dates") else "TBD",
            "month": url_data.get("month", ""),
            "year": url_data.get("year", ""),
            "key_topics": url_data.get("key_topics", []),
            "session_count": url_data.get("session_count", "200+"),
            "speaker_count": url_data.get("speaker_count", "50+"),
        }
        _log.info(f"[CONTENT] Event data: {event_data}")

        try:
            # detect_stage() returns a dict (name, funnel, days_to_event, ...), not the
            # plain AI-template stage key generate_variation_b_email() expects — extract
            # the funnel stage name, then map it onto the AI template library's own key.
            detected_stage_dict = detect_stage(url_data.get("event_dates", []))
            detected_stage_name = detected_stage_dict.get("name", "Unknown")
            ai_template_key = ai_email_templates.map_funnel_stage_to_ai_template(detected_stage_name)
            _log.info(f"[CONTENT] ✅ Detected funnel stage: {detected_stage_name} → AI template: {ai_template_key}")
        except Exception as stage_err:
            _log.error(f"[CONTENT] ❌ Stage detection failed: {stage_err}")
            detected_stage_name = "Unknown"
            ai_template_key = "CFP Launch"

        _log.info(f"[CONTENT] Calling generate_variation_b_email({ai_template_key}, ...)")
        variant_a_data = generate_ai_content.generate_variation_b_email(ai_template_key, event_data)
        _log.info(f"[CONTENT] ✅ AI generation complete. Keys: {list(variant_a_data.keys())}")

        if variant_a_data.get("error"):
            _log.error(f"[CONTENT] ❌ AI generation error: {variant_a_data.get('error')}")
            raise Exception(f"AI generation failed: {variant_a_data.get('error')}")

        if not variant_a_id:
            _log.error("[CONTENT] ❌ No base email_id available for Variant A")
            raise Exception("email_id not set")

        # Apply AI-generated settings + content to the base email (Variant A)
        try:
            _log.info(f"[CONTENT] Updating Variant A settings: subject='{variant_a_data.get('subject')}'")
            hubspot_tools.update_email_settings(
                variant_a_id,
                subject=variant_a_data.get("subject", ""),
                from_name=from_name,
                from_address=from_address,
            )
            _log.info(f"[CONTENT] ✅ Updated Variant A settings")
        except Exception as settings_err:
            _log.error(f"[CONTENT] ⚠️  Error updating Variant A settings: {settings_err}")
            # Don't fail completely - continue to content update

        try:
            html_content = variant_a_data.get("html", variant_a_data.get("body", ""))
            _log.info(f"[CONTENT] Updating Variant A content ({len(html_content)} chars)")
            hubspot_tools.update_email_content(
                variant_a_id,
                html_content=html_content,
            )
            _log.info(f"[CONTENT] ✅ Updated Variant A content")
        except Exception as content_err:
            _log.error(f"[CONTENT] ⚠️  Error updating Variant A content: {content_err}")
            # Don't fail completely - variant A email still exists

        _log.info(f"[CONTENT] ✅ Variant A (AI Template) complete: {variant_a_id}")

    except Exception as e:
        _log.error(f"[CONTENT] ❌ CRITICAL: Variant A generation failed: {e}", exc_info=True)
        variant_a_data = {}

    # Step 2: Create Variant B as a true HubSpot A/B variation of Variant A
    _log.info("[CONTENT] Starting Variant B (User Content) creation...")
    variant_b_id = ""

    if not variant_a_id:
        _log.error("[CONTENT] ❌ No variant_a_id available for A/B variation")
    else:
        _log.info(f"[CONTENT] Creating A/B variation from Variant A ({variant_a_id})...")
        try:
            variant_b_name = f"{email_name} - Variant B (User Content)"
            ab_result = hubspot_tools.create_ab_variation(variant_a_id, variant_b_name)
            _log.info(f"[CONTENT] A/B variation result: {ab_result}")

            if ab_result.get("status") != "success":
                _log.error(f"[CONTENT] ❌ A/B variation failed: {ab_result.get('error')}")
                raise Exception(f"A/B variation creation failed: {ab_result.get('error')}")

            variant_b_id = ab_result.get("variant_id", "")

            if not variant_b_id:
                _log.error(f"[CONTENT] ❌ No variant_id returned from A/B variation API")
                raise Exception(f"A/B variation API returned no variant ID: {ab_result}")

            _log.info(f"[CONTENT] ✅ Created A/B variation: variant_b_id={variant_b_id}")

        except Exception as ab_err:
            _log.error(f"[CONTENT] ❌ A/B variation exception: {ab_err}")
            variant_b_id = ""

    # Step 3: Let agent apply user content to Variant B, then restore its own subject
    # (the new variation inherits Variant A's AI subject at creation time; re-apply the
    # base/clone-time subject here so the two variants stay distinguishable for testing).
    variant_b_analysis = {}
    if variant_b_id:
        try:
            hubspot_tools.update_email_settings(variant_b_id, subject=base_subject)
        except Exception as restore_err:
            _log.warning(f"[CONTENT] ⚠️  Could not restore Variant B subject: {restore_err}")

        prompt_variant_b = (
            f"Create Variant B (User Content) email:\n"
            f"Content provided:\n{content_input}\n{variant_note}\n\n"
            f"STEPS:\n"
            f"1. Call fetch_content to convert user content → clean HTML\n"
            f"2. Call update_email_content with email_id={variant_b_id} and the HTML\n"
            f"3. Return success status\n"
        )

        agent_result, messages = run_turn(session.messages, prompt_variant_b)
        session.messages = messages

        # Step 3.5: Analyze and optimize Variant B (user-provided) content
        _log.info("[CONTENT] ===== VARIANT B ANALYSIS PHASE =====")
        try:
            _log.info(f"[CONTENT] Fetching Variant B details from HubSpot (ID: {variant_b_id})")
            variant_b_email = hubspot_tools.get_email_details(variant_b_id)

            if variant_b_email:
                variant_b_subject_raw = variant_b_email.get("subject", "")
                variant_b_preview = variant_b_email.get("preview", "")
                variant_b_body = variant_b_email.get("html", "")

                _log.info(f"[CONTENT] ✅ Retrieved Variant B: subject='{variant_b_subject_raw[:50]}...'")

                _log.info("[CONTENT] 🔍 Running AI analysis on Variant B content...")
                event_type = session.meta.get("stage_name", "General Event")
                analysis_result = analyze_email_content.analyze_and_improve_email(
                    email_subject=variant_b_subject_raw,
                    email_body=variant_b_body,
                    email_preview=variant_b_preview,
                    event_data=url_data,
                    event_type=event_type
                )

                if analysis_result and not analysis_result.get("error"):
                    variant_b_analysis = analysis_result
                    _log.info(f"[CONTENT] ✅ Analysis complete. Score: {analysis_result.get('overall_score', 0)}/10")

                    improved_email = analysis_result.get("improved_email", {})
                    improved_subject = improved_email.get("subject", "")
                    improved_preview = improved_email.get("preview", "")
                    improved_body = improved_email.get("body", "")

                    if analysis_result.get("overall_score", 0) < 8 and improved_subject:
                        _log.info("[CONTENT] 🚀 Applying improvements to Variant B...")
                        try:
                            if improved_subject and improved_subject != variant_b_subject_raw:
                                _log.info(f"[CONTENT] Updating subject: '{variant_b_subject_raw[:40]}...' → '{improved_subject[:40]}...'")
                                hubspot_tools.update_email_settings(
                                    variant_b_id,
                                    subject=improved_subject,
                                    preview=improved_preview if improved_preview else None
                                )

                            if improved_body and improved_body != variant_b_body:
                                _log.info(f"[CONTENT] Updating email body ({len(improved_body)} chars)")
                                hubspot_tools.update_email_content(
                                    variant_b_id,
                                    html_content=improved_body
                                )

                            _log.info("[CONTENT] ✅ Improvements applied successfully")

                            session.meta["variant_b_improvements_applied"] = True
                            session.meta["variant_b_original_subject"] = variant_b_subject_raw
                            session.meta["variant_b_improved_subject"] = improved_subject

                        except Exception as improve_err:
                            _log.warning(f"[CONTENT] ⚠️  Could not apply improvements: {improve_err}")
                            # Continue anyway - analysis still valuable
                    else:
                        _log.info("[CONTENT] ℹ️  Analysis score >= 8 or no improvements needed, keeping original")
                else:
                    _log.warning(f"[CONTENT] ⚠️  Analysis returned error: {analysis_result.get('error', 'Unknown error')}")
            else:
                _log.warning("[CONTENT] ⚠️  Could not fetch Variant B details from HubSpot")

        except Exception as analysis_err:
            _log.warning(f"[CONTENT] ⚠️  Analysis phase failed (non-critical): {analysis_err}", exc_info=True)
            # Continue with rest of flow - analysis is optional enhancement
    else:
        _log.error("[CONTENT] ❌ Skipping Variant B content application — no variant_b_id")

    # Step 4: Format and return final output with both variants and analysis
    variant_a_subject = variant_a_data.get("subject", "")
    variant_b_subject = session.meta.get("variant_b_improved_subject", "") or base_subject

    # Log final state
    _log.info(f"[CONTENT] Final state: variant_a_id={variant_a_id}, variant_b_id={variant_b_id}")

    # Determine status
    variant_a_status = "✅ Created" if variant_a_id else "❌ Missing"
    variant_b_status = "✅ Created" if variant_b_id else "❌ Generation Failed"

    # Build analysis section if available
    analysis_section = ""
    if variant_b_analysis:
        analysis_section += (
            f"\n════════════════════════════════════════════════════════════════════════════════\n"
            f"🔍 VARIATION B - AI CONTENT ANALYSIS & OPTIMIZATION\n"
            f"════════════════════════════════════════════════════════════════════════════════\n\n"
        )

        # Overall score
        overall_score = variant_b_analysis.get("overall_score", 0)
        score_indicator = "🟢" if overall_score >= 8 else "🟡" if overall_score >= 6 else "🔴"
        analysis_section += f"{score_indicator} Email Quality Score: {overall_score}/10\n\n"

        # Summary
        summary = variant_b_analysis.get("summary", "")
        if summary:
            analysis_section += f"📝 Summary:\n{summary}\n\n"

        # Improvements applied or suggested
        improvements = variant_b_analysis.get("improvements", [])
        if improvements:
            improvements_applied = session.meta.get("variant_b_improvements_applied", False)
            if improvements_applied:
                analysis_section += "✅ IMPROVEMENTS APPLIED:\n"
            else:
                analysis_section += "💡 IMPROVEMENT SUGGESTIONS:\n"

            for i, improvement in enumerate(improvements[:5], 1):  # Show top 5
                category = improvement.get("category", "").replace("_", " ").title()
                issue = improvement.get("issue", "")
                recommendation = improvement.get("recommendation", "")
                impact = improvement.get("impact", "")

                analysis_section += f"\n{i}. {category}\n"
                analysis_section += f"   Issue: {issue}\n"
                analysis_section += f"   Recommendation: {recommendation}\n"
                if impact:
                    analysis_section += f"   Impact: {impact}\n"

            if len(improvements) > 5:
                analysis_section += f"\n... and {len(improvements) - 5} more improvements\n"

        if improvements_applied:
            original_subject = session.meta.get("variant_b_original_subject", "")
            improved_subject = session.meta.get("variant_b_improved_subject", "")
            if original_subject and improved_subject:
                analysis_section += (
                    f"\n📌 Key Change:\n"
                    f"   Original: {original_subject}\n"
                    f"   Improved: {improved_subject}\n"
                )

    output = (
        f"\n════════════════════════════════════════════════════════════════════════════════\n"
        f"📧 A/B TESTING SETUP RESULT\n"
        f"════════════════════════════════════════════════════════════════════════════════\n\n"
        f"🔄 SIDE-BY-SIDE COMPARISON\n\n"
        f"VARIATION A (AI-Generated Template)        VARIATION B (User Content)\n"
        f"─────────────────────────────────────────────────────────────────────────────\n"
        f"Status:           {variant_a_status}                      {variant_b_status}\n"
        f"Email ID:         {variant_a_id or 'N/A'}                    {variant_b_id or 'N/A'}\n"
        f"Subject:          {(variant_a_subject[:40] + '...') if len(variant_a_subject) > 40 else variant_a_subject}\n"
        f"                  {(variant_b_subject[:40] + '...') if len(variant_b_subject) > 40 else variant_b_subject}\n"
        f"Type:             AI-Generated             User-Created\n"
        f"Template:         {ai_template_key}         Custom\n"
        f"Funnel Stage:     {detected_stage_name}\n"
        f"─────────────────────────────────────────────────────────────────────────────\n\n"
        f"🤖 VARIATION A DETAILS\n"
        f"  ✓ Status: {variant_a_status}\n"
        f"  ✓ Email ID: {variant_a_id}\n"
        f"  ✓ Subject: {variant_a_subject}\n"
        f"  ✓ Type: AI-Generated ({ai_template_key}, mapped from funnel stage '{detected_stage_name}')\n"
        + (f"  ⚠️  Mode: template-only — ANTHROPIC_API_KEY not configured, so this is placeholder copy, not Claude-written content\n" if not ANTHROPIC_API_KEY else "")
        + f"  ✓ Link: https://app.hubspot.com/content/emails/{variant_a_id}\n\n"
        f"📊 VARIATION B DETAILS\n"
        f"  ✓ Status: {variant_b_status}\n"
        f"  ✓ Email ID: {variant_b_id or 'Generation failed'}\n"
        f"  ✓ Subject: {variant_b_subject}\n"
        f"  ✓ Type: User-provided content\n"
        f"  ✓ Link: {f'https://app.hubspot.com/content/emails/{variant_b_id}' if variant_b_id else 'N/A'}\n\n"
    )

    # Add analysis section if available
    output += analysis_section

    if variant_a_id and variant_b_id:
        output += (
            f"════════════════════════════════════════════════════════════════════════════════\n"
            f"✅ A/B TEST CREATED SUCCESSFULLY\n"
            f"════════════════════════════════════════════════════════════════════════════════\n\n"
            f"🎯 A/B TEST SETUP\n"
            f"─────────────────────────────────────────────────────────────────────────────\n"
            f"Variant A (Base): {variant_a_id} - AI-generated template\n"
            f"Variant B:        {variant_b_id} - User-provided content (linked via HubSpot A/B API)\n"
            f"Status:           ✅ Ready for deployment\n"
            f"─────────────────────────────────────────────────────────────────────────────\n\n"
            f"🚀 NEXT STEPS\n"
            f"─────────────────────────────────────────────────────────────────────────────\n"
            f"1. Go to HubSpot → Campaigns → Email Settings\n"
            f"2. Find your email campaign\n"
            f"3. View A/B Test → Edit (or send directly if ready)\n"
            f"4. Set audience split: 50/50 (recommended)\n"
            f"5. Choose winner selection method:\n"
            f"   - Open rate (most common)\n"
            f"   - Click rate\n"
            f"   - Conversion rate\n"
            f"6. Set test duration\n"
            f"7. Review and send\n"
            f"\n"
            f"📊 TIPS FOR SUCCESS\n"
            f"─────────────────────────────────────────────────────────────────────────────\n"
            f"• Variant A subject: {(variant_a_subject[:60] + '...') if len(variant_a_subject) > 60 else variant_a_subject}\n"
            f"• Variant B subject: {(variant_b_subject[:60] + '...') if len(variant_b_subject) > 60 else variant_b_subject}\n"
            f"• Both variations use the same template structure\n"
            f"• Only subject and content differ between variants\n"
            f"• Recommended test variable: Subject Line\n"
            f"════════════════════════════════════════════════════════════════════════════════\n"
        )
    elif variant_a_id and not variant_b_id:
        output += (
            f"════════════════════════════════════════════════════════════════════════════════\n"
            f"⚠️  PARTIAL: Only Variant A was created\n"
            f"════════════════════════════════════════════════════════════════════════════════\n\n"
            f"Variant B (A/B variation) failed to create. Check:\n"
            f"  1. HubSpot create-ab-variation API call succeeded (check server logs)\n"
            f"  2. An active variation doesn't already exist for email {variant_a_id}\n"
            f"     (HubSpot won't create a new one if it does)\n"
            f"  3. Check server logs for detailed error messages\n"
            f"\nYou can manually create the A/B variation in HubSpot's UI, or try again.\n"
            f"════════════════════════════════════════════════════════════════════════════════\n"
        )
    else:
        output += (
            f"════════════════════════════════════════════════════════════════════════════════\n"
            f"❌ ERROR: Neither variant was created\n"
            f"════════════════════════════════════════════════════════════════════════════════\n"
            f"Check: Agent failed to create Variant A. Review logs for details.\n"
        )

    return output, messages


def chat_turn(session, message: str) -> tuple[str, list]:
    return run_turn(session.messages, message)


def extract_variant_id_from_messages(messages: list) -> str | None:
    """Extract variant_id from agent or user messages if one was selected."""
    for msg in reversed(messages):
        content = msg.get("content", [])
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            # Check tool result for select_template_variant calls
            if block.get("type") == "tool_result":
                try:
                    data = json.loads(block.get("content", "{}"))
                    if data.get("selected") and data.get("variant_id"):
                        return data.get("variant_id")
                except Exception:
                    pass
            # Check text for "Use variant v*" patterns
            text = block.get("text", "")
            if isinstance(text, str) and "use variant" in text.lower():
                import re
                m = re.search(r"use\s+variant\s+([v\d_a-z]+)", text, re.IGNORECASE)
                if m:
                    return m.group(1)
    return None


def extract_brand_history_from_messages(messages: list) -> dict | None:
    """
    Scan plan-phase messages to find brand/event history for the clone phase.
    Checks both SDK-style tool_result blocks (Anthropic API mode) and
    __tool_log__ entries (Claude Code CLI mode).
    """
    def _check_block(block: dict) -> dict | None:
        if block.get("type") != "tool_result":
            return None
        try:
            data = json.loads(block.get("content", "{}"))
            has_id = data.get("matched_email_id") or data.get("last_email_id")
            if data.get("found") and has_id:
                # Normalise search_emails_for_event → same keys as lookup_brand_history
                if "matched_email_id" in data and "last_email_id" not in data:
                    data["last_email_id"]   = data["matched_email_id"]
                    data["last_email_name"] = data.get("matched_email_name", "")
                return data
        except Exception:
            pass
        return None

    for msg in messages:
        role    = msg.get("role", "")
        content = msg.get("content", [])

        # Claude Code CLI mode — tool results stored in __tool_log__ message
        if role == "__tool_log__" and isinstance(content, list):
            for block in content:
                result = _check_block(block)
                if result:
                    return result

        # Anthropic SDK mode — tool results in regular message content lists
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                result = _check_block(block)
                if result:
                    return result

    return None


def extract_email_id_from_messages(messages: list) -> str | None:
    for msg in reversed(messages):
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                try:
                    data = json.loads(block.get("content", "{}"))
                    if "email_id" in data:
                        return data["email_id"]
                except Exception:
                    pass
    return None
