# Where Multiple Variants Are Created

## File Location: `backend/email_templates.py`

### Main Dictionary: STAGE_TEMPLATES (Line 26)

```python
STAGE_TEMPLATES: dict[str, dict] = {
    # Each stage is a key
    # Each stage contains a "variants" array
    # Each array contains multiple variant objects
}
```

---

## STRUCTURE: How Variants Are Organized

```
STAGE_TEMPLATES (Main Dictionary)
│
├─ "Event Announcement" (Stage Name)
│  └─ "variants": [] (Array of variants)
│     ├─ [0] v1_value_focused (Variant 1)
│     ├─ [1] v2_urgency_focused (Variant 2)
│     └─ [2] v3_social_proof (Variant 3)
│
├─ "Registration Launch" (Stage Name)
│  └─ "variants": [] (Array of variants)
│     ├─ [0] v1_discount_focused
│     ├─ [1] v2_value_focused
│     └─ [2] v3_social_proof
│
├─ "Schedule Announcement" (Stage Name)
│  └─ "variants": [] (Array of variants)
│     ├─ [0] v1_keynote_focused
│     ├─ [1] v2_session_focused
│     └─ [2] v3_networking_focused
│
├─ "Final Countdown" (Stage Name)
│  └─ "variants": [] (Array of variants)
│     ├─ [0] v1_fomo_urgency
│     ├─ [1] v2_last_chance
│     └─ [2] v3_social_proof_testimonial
│
└─ [Other 9 stages with single variants]
   └─ "variants": []
      └─ [0] v1_main
```

---

## Each Variant Contains 5 Fields

```python
{
    "id": "v1_value_focused",              # Unique identifier
    "label": "Value-Focused Messaging",    # Human-readable name
    "strategy": "Emphasizes learning...",  # Marketing strategy description
    "subject": "Save the Date: [Event Name]...",   # Email subject line
    "preheader": "Join 10,000+ developers...",      # Preview text
    "body": "Hi {{first_name}},..."        # Full email body
}
```

---

## LINE-BY-LINE EXAMPLE: Event Announcement Stage

### File: `backend/email_templates.py`
### Lines: 28-128

```
Line 28:    "Event Announcement": {
Line 29:        "variants": [
Line 30:            {
Line 31:                "id": "v1_value_focused",
Line 32:                "label": "Value-Focused Messaging",
Line 33:                "strategy": "Emphasizes learning, networking, and community value",
Line 34:                "subject": "Save the Date: [Event Name] is Coming to [City]!",
Line 35:                "preheader": "Join 10,000+ developers [Dates] in [City]...",
Line 36-57:             "body": """Hi {{first_name}},
                        
                        The wait is over. [Event Name] 2026 dates are officially here.
                        ...
                        """,
Line 58:            },
Line 59:            {
Line 60:                "id": "v2_urgency_focused",
Line 61:                "label": "Urgency & Savings Focus",
Line 62:                "strategy": "Highlights early bird savings and limited-time advantage",
Line 63:                "subject": "🚨 Early Bird Alert: [Event Name] Dates Just Announced – Save $300",
Line 64:                "preheader": "Early bird opens [Date]...",
Line 65-90:             "body": """Hi {{first_name}},
                        
                        The [Event Name] 2026 dates are officially locked in...
                        """,
Line 91:            },
Line 92:            {
Line 93:                "id": "v3_social_proof",
Line 94:                "label": "Social Proof & Community",
Line 95:                "strategy": "Focuses on community size, past attendee testimonials, and FOMO",
Line 96:                "subject": "10,000+ Developers Are Already Saying Yes to [Event Name]...",
Line 97:                "preheader": "Join the community | Past attendees rave...",
Line 98-125:            "body": """Hi {{first_name}},
                        
                        [Event Name] 2026 is happening [Dates] in [City]...
                        """,
Line 126:            },
Line 127:        ]
Line 128:    },
```

---

## Stages with Multiple Variants (4 stages × 3 variants each)

### 1. Event Announcement (Lines 28-128)
- **v1_value_focused** (Lines 31-57)
  - Focus: Learning, networking, community
  - Subject: "Save the Date"
  - Tone: Informational, exciting
  
- **v2_urgency_focused** (Lines 60-90)
  - Focus: Early bird savings, $300 discount
  - Subject: "Early Bird Alert"
  - Tone: Urgent, time-limited
  
- **v3_social_proof** (Lines 93-125)
  - Focus: Past attendees, testimonials, FOMO
  - Subject: "10,000+ Developers Are Already Saying Yes"
  - Tone: Community-driven, aspirational

### 2. Registration Launch (Lines ~150-350)
- **v1_discount_focused**: Price/savings lead
- **v2_value_focused**: ROI and what you get
- **v3_social_proof**: Attendee counts, testimonials

### 3. Schedule Announcement (Lines ~400-600)
- **v1_keynote_focused**: Speaker lineup highlighted
- **v2_session_focused**: Sessions and track variety
- **v3_networking_focused**: Networking and hallway track

### 4. Final Countdown (Lines ~700-900)
- **v1_fomo_urgency**: FOMO messaging, hard deadline
- **v2_last_chance**: "One more chance" friendly tone
- **v3_social_proof_testimonial**: Testimonials, others attending

---

## Stages with Single Variant (9 stages × 1 variant each)

### Lines 130-487 (Approximate)

- CFP Launch (v1_main)
- Co-Located Events + CFP Reminder (v1_main)
- DEI & Travel Fund (v1_main)
- Event Week (v1_main)
- Thank You + Survey (v1_main)
- Content & Recordings Release (v1_main)
- Next Event CFP Teaser (v1_main)
- Community Nurture (v1_main)
- Main Registration Push (original template)

---

## How Variants Are ACCESSED

### In Code (backend/agent.py):

1. **Get all variants for a stage:**
```python
variants = email_templates.get_template_variants("Event Announcement")
# Returns: [v1, v2, v3] objects
```

2. **Get specific variant:**
```python
variant = email_templates.get_template_variant("Event Announcement", "v2_urgency_focused")
# Returns: {id, label, strategy, subject, preheader, body}
```

3. **Get variant metadata for display:**
```python
strategies = email_templates.list_variant_strategies("Event Announcement")
# Returns: [{id, label, strategy}, {id, label, strategy}, ...]
```

4. **Get first/default variant:**
```python
variant = email_templates.get_template("Event Announcement")
# Returns: First variant (v1_value_focused)
```

---

## WORKFLOW: Where Variants Are USED

### Phase 1: PLAN (agent.py, plan_turn function)

```
User provides event URL
  ↓
Agent detects stage: "Event Announcement"
  ↓
Agent calls: get_variant_strategies("Event Announcement")
  ↓
Function (email_templates.py, line ~543) returns:
  [
    {id: "v1_value_focused", label: "...", strategy: "..."},
    {id: "v2_urgency_focused", label: "...", strategy: "..."},
    {id: "v3_social_proof", label: "...", strategy: "..."}
  ]
  ↓
Agent shows to user with description
```

**Location in agent.py:** Line 1367-1421 in plan_turn()

### Phase 2: CLONE (agent.py, clone_turn function)

```
User chooses variant: "v2_urgency_focused"
  ↓
clone_turn() calls extract_variant_id_from_messages()
  ↓
Returns: "v2_urgency_focused"
  ↓
Calls _get_variant_subject_preview("Event Announcement", "v2_urgency_focused", event_data)
  ↓
Function retrieves variant from STAGE_TEMPLATES
  ↓
Fills placeholders: [Event Name] → "KubeCon", [City] → "Barcelona"
  ↓
Returns: (subject, preview) ready for HubSpot
  ↓
Stores: session.meta["selected_variant_id"] = "v2_urgency_focused"
```

**Location in agent.py:** Line 1461-1488 in clone_turn()

### Phase 3: CONTENT (agent.py, content_turn function)

```
content_turn() retrieves: session.meta["selected_variant_id"]
  ↓
Retrieves variant from STAGE_TEMPLATES
  ↓
Gets strategy: "Highlights early bird savings and limited-time advantage"
  ↓
Gets body template: "The moment you've been waiting for..."
  ↓
Passes to agent:
  "MESSAGING VARIANT SELECTED: v2_urgency_focused
   Strategy: Highlights early bird savings and limited-time advantage
   Template structure: [shows first 500 chars]"
  ↓
Agent uses this as guidance for merging user content
```

**Location in agent.py:** Line 1674-1698 in content_turn()

---

## Summary: WHERE VARIANTS ARE CREATED

| Aspect | Location | Details |
|--------|----------|---------|
| **File** | `backend/email_templates.py` | Single file contains all variants |
| **Data Structure** | `STAGE_TEMPLATES` dict (Line 26) | Python dictionary with nested structure |
| **Variant Definitions** | Lines 28-487 | Hardcoded in Python |
| **Number of Variants** | 12 total | 4 stages × 3 variants + 8 stages × 1 variant |
| **Variant Format** | Each has 5 fields | id, label, strategy, subject, preheader, body |
| **Helper Functions** | Lines 490-548 | 5 functions to access variants |
| **Usage in Agent** | `agent.py` | 7 helper functions + 4 function updates |

---

## How to Add More Variants

1. Open `backend/email_templates.py`
2. Find the stage (e.g., "Event Announcement")
3. Add new dict to the "variants" array:

```python
{
    "id": "v4_new_variant",           # Must be unique
    "label": "New Variant Name",       # Display name
    "strategy": "Description...",      # Marketing approach
    "subject": "Subject line...",      # Email subject
    "preheader": "Preview text...",    # Email preheader
    "body": """Email body..."""        # Full email body
}
```

4. Restart the server
5. New variant appears in `get_variant_strategies()` calls

---

## Quick Reference: Variant Structure

```
STAGE_TEMPLATES
└─ "Event Announcement"
   └─ "variants" (Array)
      └─ Variant Object
         ├─ "id": "v1_value_focused"
         ├─ "label": "Value-Focused Messaging"
         ├─ "strategy": "Emphasizes learning..."
         ├─ "subject": "Save the Date..."
         ├─ "preheader": "Join 10,000+..."
         └─ "body": "Hi {{first_name}},..."
```

**All variants are STATIC** — defined once in the file, loaded into memory when the module imports.
