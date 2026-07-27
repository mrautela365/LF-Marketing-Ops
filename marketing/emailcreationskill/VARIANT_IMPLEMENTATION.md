# Email Template Variants & A/B Testing Implementation

**Status**: ✅ COMPLETE (Phases 1-3)

## What Was Implemented

### Phase 1: Data Structure ✅
- Extended `email_templates.py` to support multiple messaging variants per stage
- Created variant templates for 4 high-priority stages (Event Announcement, Registration Launch, Schedule Announcement, Final Countdown)
- Each stage now has 2-3 variants with different messaging strategies:
  - **Event Announcement**: Value-focused, Urgency-focused, Social Proof
  - **Registration Launch**: Discount-focused, ROI-focused, Social Proof
  - **Schedule Announcement**: Keynote-focused, Session-focused, Networking-focused
  - **Final Countdown**: FOMO/Urgency, Last Chance, Social Proof
- Remaining 9 stages wrapped in single-variant format (backward compatible)
- Helper functions: `get_template()`, `get_template_variants()`, `get_template_variant()`, `list_variant_strategies()`

### Phase 2: Agent Tools ✅
- Added `get_variant_strategies(stage_name)` tool
  - Lists available messaging strategies for a stage
  - Returns variant id, label, and strategy description
  - Called during plan phase to show options
  
- Added `select_template_variant(stage_name, variant_id, reason)` tool
  - Lets agent/user explicitly choose a variant
  - Records selection with reasoning
  - Logs for audit trail

### Phase 3: Agent Integration ✅
- **Plan Phase**: 
  - Updated SYSTEM_PROMPT to mention variant selection capability
  - plan_turn() now includes messaging variant recommendation section
  - Shows all available variants for the detected stage
  - Recommends one with rationale; user can choose different one
  
- **Clone Phase**:
  - Extracts variant selection from user messages (via `extract_variant_id_from_messages()`)
  - Falls back to recommended variant if user didn't specify
  - Generates subject line and preview text from selected variant
  - Stores `selected_variant_id` in session.meta for content phase
  - Fills template placeholders ([Event Name], [City], [Dates], etc.)

- **Content Phase**:
  - content_turn() now includes variant context in prompt
  - Passes variant strategy to agent as guidance
  - Agent uses variant template structure while integrating user content
  - Maintains messaging strategy throughout

### Helper Functions Added
- `_recommend_variant_strategy(stage_name)` → returns (variant_id, reason)
- `_format_variant_recommendations(stage_name)` → formats options for display
- `_get_variant_subject_preview(stage_name, variant_id, event_data)` → generates filled subject/preview
- `_fill_template_placeholders(template_text, event_data)` → replaces [Event Name], [City], etc.
- `extract_variant_id_from_messages(messages)` → parses user's variant choice

## How It Works

### User Flow
1. **Plan Phase**: User provides event URL
   - System detects stage (e.g., "Event Announcement")
   - Shows available variants with descriptions
   - Recommends best variant for the stage
   - User can accept recommended or say "Use variant v2_urgency_focused"

2. **Clone Phase**: System selects variant
   - Extracts user's variant choice if specified
   - Generates subject + preview from variant template
   - Fills placeholders with event data
   - Clones HubSpot email with these settings

3. **Content Phase**: User provides content
   - System provides variant messaging strategy to agent
   - Agent merges user content with variant structure
   - Maintains messaging approach (urgency vs value vs social proof)
   - Returns final draft ready for review

## Backward Compatibility
- All functions default to first variant if none specified
- Existing code calling `get_template(stage)` still works
- Single-variant stages behave identically to before
- No breaking changes to API or HubSpot integration

## Testing
All integration tests passing:
- ✅ Variant recommendation by stage
- ✅ Subject/preview generation from variants
- ✅ Variant options formatting
- ✅ Variant extraction from messages
- ✅ Tool execution for variant selection
- ✅ End-to-end data structure and helpers

## Next Steps (Phase 4 - Not Yet Implemented)

### Frontend UI Enhancement
- Add dropdown selector after Plan phase to visually choose variant
- Show variant preview/comparison before confirming
- Display which variant is being used in clone confirmation

### Optional Enhancements
- Store variant performance metrics (open rate, CTR) from HubSpot campaigns
- Feed back recommendations based on past performance
- Allow admins to add/edit variants without code changes
- A/B test results dashboard

## Files Modified
- `backend/email_templates.py` — Variant data structure + helpers
- `backend/agent.py` — Variant tools + integration logic

## Known Limitations (Per HubSpot Constraints)
- HubSpot only supports element-level A/B testing, not template-level
- A/B testing only works in standard sequences, not dynamic sequences
- Template-level testing would require manual workarounds or custom solutions
- Current implementation supports user's goal: multiple content versions within same responsive layout

## Usage Example
```python
# Get available variants for a stage
strategies = email_templates.list_variant_strategies("Final Countdown")
# Output: [
#   {"id": "v1_fomo_urgency", "label": "FOMO & Fear-Based Urgency", "strategy": "..."},
#   {"id": "v2_last_chance", "label": "Last Chance & One More Thing", "strategy": "..."},
#   {"id": "v3_social_proof_testimonial", "label": "Social Proof & Testimonials", "strategy": "..."}
# ]

# Get a specific variant
variant = email_templates.get_template_variant("Final Countdown", "v1_fomo_urgency")
# Variant contains: id, label, strategy, subject, preheader, body

# Agent can now recommend or let user select which messaging to use
```
