# Email Template Usage Guide

## Overview

Templates are stored in two places and work together:

1. **STAGE_TEMPLATES** — General event marketing templates by stage (13 stages × 1-3 variants each)
2. **BEST_PRACTICE_TEMPLATES** — Proven B2B event templates from ArgoCon analysis (5 high-conversion templates)

---

## How Templates Are Used in the Workflow

### PHASE 1: PLAN

When user provides event URL, the system:

1. **Detects the marketing stage** (Event Announcement, Registration Launch, etc.)
2. **Looks up STAGE_TEMPLATES** to show all variants available
3. **Recommends BEST_PRACTICE_TEMPLATE** (if B2B event)
4. **Displays in UX:**

```
═══════════════════════════════════════════════════════════════
EMAIL STAGING PLAN — [Event Name]

[Summary paragraph about what will be staged]

### TEMPLATE RECOMMENDATION

Recommended Template: B2B Event Announcement ★★★★★
Source: ArgoCon + KeycloakCon Japan 2026
Expected Performance: 45% open rate, 12% CTR
Strategy: Build excitement + relationship focus + multiple CTAs

Template Structure:
  - Opening: Personal greeting + achievement
  - Body: 4-5 key highlights (bulleted)
  - CTAs: Soft (calendar) + Medium (prospectus) + Hard (contract)
  - Signature: Contact methods + personal touch

Why this template: Your event matches B2B sponsorship campaign pattern.
If different: Reply with "Use [Template Name]" to switch templates.

### MESSAGING VARIANTS

For this stage (Event Announcement), messaging variants available:
  - v1_value_focused: Learning + networking + community value
  - v2_urgency_focused: Early bird savings + FOMO
  - v3_social_proof: Testimonials + community size

Recommended variant: v1_value_focused (works well with announcements)
If different: Reply with "Use variant v2_urgency_focused" to switch

### STAGE & CONTENT OVERVIEW

| Field | Value |
|-------|-------|
| Current Stage | Event Announcement (Day 0 — 60 days to event) |
| Stage Goal | Build excitement + awareness + sponsorship interest |
| Email Type | Invite |
| Template Being Used | B2B_Event_Announcement |
| Messaging Variant | v1_value_focused |
| Subject Line | Save the Date: [Event Name] is Coming to [City]! |
| Preview Text | Join 10,000+ developers [Dates] in [City] \| Early bird opens soon |

### SETTINGS

| Field | Value |
|-------|-------|
| Email Name | 26Q2 - CNCF - KubeCon EU - Announcement |
| From Name | (from brand history) |
| From Address | (from brand history) |
| Email Type | BATCH_EMAIL |
| Send Date | [REQUIRED — provide below] |

### AUDIENCE

| Field | Value |
|-------|-------|
| Send List | CNCF Subscribers (15,000+ contacts) |
| Suppression Lists | Previously sent, Unsubscribes |

═══════════════════════════════════════════════════════════════

Please provide: Send Date
```

---

### PHASE 2: CLONE

User provides send date and optionally selects different template/variant.

System:
1. Extracts variant choice from user message (if provided)
2. **Generates subject/preview from template** (with placeholders filled)
3. **Stores in session:**
   - `selected_template_type` (e.g., "B2B_Event_Announcement")
   - `selected_variant_id` (e.g., "v1_value_focused")
   - `template_quality_rating` (e.g., 5)

**UX Display Before Cloning:**

```
Template Summary Before Cloning:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Template: B2B Event Announcement (★★★★★)
Variant: Value-Focused Messaging
Expected Open Rate: 45% (based on ArgoCon data)
Expected CTR: 12%

Subject Line: Save the Date: KubeCon EU 2026 is Coming to Barcelona!
Preview: Join 10,000+ developers Sep 12-14 in Barcelona | Early bird opens soon

Email Name: 26Q3 - CNCF - KubeCon EU - Announcement
From: Nicole Puopolo <events@cncf.io>
Send To: 15,000 CNCF subscribers
Send Date: August 1, 2026

Proceeding with clone...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

### PHASE 3: CONTENT

User provides content (Google Doc, HTML, text).

System:
1. Retrieves `selected_template_type` from session
2. Gets full template structure with strategy description
3. **Passes to agent with template context:**

```
🎨 MESSAGING TEMPLATE BEING USED: B2B_Event_Announcement

Strategy: Build excitement + relationship focus + multiple CTAs

Template Structure to Follow:
  1. Personal greeting with names
  2. Achievement + announcement ("officially announced")
  3. 4-5 key highlights (bulleted)
  4. Historical relationship reference (past sponsors)
  5. Multiple CTAs (soft/medium/hard commitment levels)
  6. Signature with contact methods
  7. Humanizing personal element (P.S.)

Tone: Professional + enthusiastic + relationship-focused
Expected open rate: 45%

Use the user-provided content, but maintain the template's structure
and messaging strategy throughout the email body.
```

---

## Template Files & Functions

### In `email_templates.py`

#### BEST_PRACTICE_TEMPLATES Structure

```python
BEST_PRACTICE_TEMPLATES = {
    "B2B_Event_Announcement": {
        "source": "ArgoCon + KeycloakCon Japan 2026",
        "quality_rating": 5,
        "conversion_type": "announcement",
        "sender_profile": "Sr. Global Event Partnerships Manager",
        "key_metrics": {
            "expected_open_rate": 0.45,
            "expected_ctr": 0.12
        },
        "template": {
            "id": "b2b_announcement",
            "label": "B2B Event Announcement (ArgoCon Template)",
            "strategy": "Build excitement + relationship focus + multiple CTAs",
            "subject": "[Event Name] + [Co-Location] - [Key Achievement]!",
            "preheader": "[Number]+ attendees | [City] | [Date] | Schedule live",
            "body": """Email body with placeholders..."""
        }
    },
    # ... 4 more templates
}
```

#### Helper Functions

```python
def get_best_practice_template(template_key: str) -> dict:
    """Get a specific best-practice template."""
    return BEST_PRACTICE_TEMPLATES.get(template_key)

def get_all_best_practice_templates() -> dict:
    """Get all best-practice templates."""
    return BEST_PRACTICE_TEMPLATES

def recommend_best_practice_template(campaign_type: str) -> dict:
    """
    Recommend template by campaign type.
    
    Types: announcement, speaker_conversion, multi_event_deal,
           existing_account_close, registration_launch
    
    Returns: {key, template, quality_rating, source}
    """
```

### In `agent.py`

#### Helper Functions

```python
def _recommend_best_practice_template(campaign_type: str) -> dict:
    """Recommend best template with quality rating and reason."""
    
def _compare_with_similar_emails(stage_name: str) -> dict:
    """Compare email with similar templates, return analysis."""
```

---

## Template Selection Logic

### Automatic Template Recommendation

When `plan_turn()` runs:

1. **Detects stage** from URL/event details
2. **Maps to campaign type:**
   - Event Announcement → "announcement"
   - Registration Launch → "registration_launch"
   - CFP Launch → "registration_launch"
   - Schedule Announcement → "announcement"
   - Final Countdown → "registration_launch"

3. **Calls `recommend_best_practice_template(campaign_type)`**
4. **Returns with quality rating & expected performance**

### Manual Template Override

User can reply in PLAN phase:
- "Use B2B_Strategic_Close template" → Switch to different template
- "Use variant v2_urgency_focused" → Switch messaging variant
- Both can be specified together

---

## Template Quality Ratings

| Template | Rating | Open Rate | CTR | Best For |
|----------|--------|-----------|-----|----------|
| B2B_Event_Announcement | ★★★★★ | 45% | 12% | Event schedules, launches |
| B2B_Speaker_Conversion | ★★★★★ | 52% | 18% | Converting speakers to sponsors |
| B2B_Strategic_Close | ★★★★★ | 48% | 14% | Complex multi-event deals |
| B2B_Rapid_Close | ★★★★ | 35% | 22% | Existing accounts, quick close |
| B2B_Registration_Launch | ★★★★ | 40% | 10% | Registration/CFP with urgency |

---

## UX Mock-up: Plan Phase Template Display

```
╔════════════════════════════════════════════════════════════════════════════════╗
║                        EMAIL STAGING PLAN                                      ║
╚════════════════════════════════════════════════════════════════════════════════╝

📧 EVENT: KubeCon EU 2026 (Barcelona, Sep 12-14)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎯 TEMPLATE RECOMMENDATION

  Template: B2B Event Announcement (Proven from ArgoCon)
  Quality:  ★★★★★ (5/5 stars)
  
  📊 Expected Performance:
     • Open Rate: 45% (industry avg: 25%)
     • Click Rate: 12% (industry avg: 8%)
     • Source: 156 emails analyzed from ArgoCon + KeycloakCon
  
  📋 Template Structure:
     1. Personal greeting with names
     2. Achievement announcement ("officially announced")
     3. 4-5 key highlights (schedule, sponsors, dates)
     4. Historical relationship reference
     5. Multiple CTAs (soft → hard)
     6. Signature with contact methods
     7. Personal touch (P.S. element)
  
  💡 Why This Template:
     Your event (schedule announcement) matches the ArgoCon pattern.
     This template has been proven to drive sponsorship interest and
     engagement. Structure focuses on relationship building with CTAs
     for multiple commitment levels.

  ⚙️ Want to use a different template?
     Reply: "Use B2B_Strategic_Close" or "Use B2B_Rapid_Close"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📝 MESSAGING VARIANT OPTIONS

  Available for this stage:
  
  ✓ v1_value_focused (Recommended)
    Focus: Learning + networking + community
    Best for: Early awareness, positive framing
  
  • v2_urgency_focused
    Focus: Early bird savings + limited spots
    Best for: Driving immediate registration
  
  • v3_social_proof
    Focus: Testimonials + community size
    Best for: Overcoming objections, credibility

  Want different variant? Reply: "Use variant v2_urgency_focused"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 PLAN DETAILS

Stage:           Event Announcement
Template:        B2B_Event_Announcement
Variant:         v1_value_focused
Subject:         Save the Date: KubeCon EU is Coming to Barcelona!
Preview:         Join 10,000+ developers Sep 12-14 in Barcelona
From:            Nicole Puopolo <events@cncf.io>
Send To:         15,000 CNCF Subscribers
Send Date:       [REQUIRED]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✍️ NEXT STEP: Provide send date (e.g., "August 1, 2026")
```

---

## Implementation Checklist

- [x] Best-practice templates stored in `BEST_PRACTICE_TEMPLATES` dict
- [x] Template quality ratings (1-5 stars) with expected metrics
- [x] Helper functions for template lookup and recommendation
- [x] Agent updated with template recommendation logic
- [x] SYSTEM_PROMPT updated with template guidance
- [x] Plan output format includes template display
- [x] Template comparison logic in agent
- [ ] Frontend updates to display templates (FE work)
- [ ] A/B testing to validate template performance (ongoing)

---

## Benefits of This Approach

1. **Data-Driven** — Templates from real campaigns with proven metrics
2. **Guidance** — Agent recommends best template with reasoning
3. **Flexibility** — User can choose different template if preferred
4. **Transparency** — Clear display of which template is being used
5. **Consistency** — Structure ensures proven success patterns
6. **Improvement** — Metrics allow ongoing optimization

---

## Next Steps

1. **FE Integration** — Display template recommendation in UI
2. **Testing** — A/B test template variations
3. **Expansion** — Add more templates as new campaigns succeed
4. **Analytics** — Track which templates convert best by industry/audience
5. **Personalization** — Adjust recommendations based on prior results
