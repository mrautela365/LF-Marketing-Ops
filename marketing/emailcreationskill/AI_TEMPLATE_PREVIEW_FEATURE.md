# AI Template Approach - Preview Feature

## Problem Solved

**Before**: AI template approach generated email and cloned directly to HubSpot without user review
- ❌ Users couldn't see what was being created
- ❌ No approval step
- ❌ No ability to refine before cloning

**After**: AI template approach shows preview first, waits for approval
- ✅ Users see exactly what will be created
- ✅ Subject line, preview text, and full email shown
- ✅ User must approve before cloning
- ✅ Can request refinements if needed

---

## User Flow

### AI Template Approach - Updated Flow

```
Step 1-3: Plan → Audience (same as before)
    ↓
Step 4: Implementation
    ├─ System generates email from AI template
    ├─ SHOWS PREVIEW:
    │  ├─ Subject line
    │  ├─ Preview text
    │  └─ Full email HTML preview
    │
    ├─ WAITS FOR USER:
    │  ├─ "yes" / "create" → Approve and clone
    │  └─ "refine" / "adjust" → Describe changes
    │
    └─ Upon approval:
       ├─ Clone to HubSpot
       ├─ Update settings
       ├─ Update content
       └─ Return email ID
```

---

## User Experience

### Phase 1: Preview Shown

```
════════════════════════════════════════════════════════════════════════════════
🤖 AI-GENERATED EMAIL PREVIEW
════════════════════════════════════════════════════════════════════════════════

Campaign Stage: CFP Launch
Quality: Based on best practices

📧 PREVIEW
─────────────────────────────────────────────────────────────────────────────
Subject:        🎤 CFP Alert: Submit to Speak at PyConf EU - Deadline Sept 1
Preview Text:   Be a speaker. Submit your talk now.
─────────────────────────────────────────────────────────────────────────────

[Full email preview shown in HTML iframe]

✅ APPROVE & CREATE
Reply with 'create' or 'yes' to clone this email to HubSpot
Reply with 'refine' or describe changes to regenerate with adjustments

💡 TIP: You can ask me to adjust the tone, add specific details, or change the focus
════════════════════════════════════════════════════════════════════════════════
```

### Phase 2: Awaiting Approval

User can:
1. **Approve**: Reply "yes", "create", "ok", "approve", "go", "proceed"
   - Email cloned to HubSpot
   - Settings and content updated
   - Ready to send
   
2. **Refine**: Reply "refine", "adjust", "change", "edit", "modify"
   - Describe desired changes
   - Claude discusses adjustments
   - Can regenerate if needed
   
3. **Reject**: Start over with different approach

### Phase 3: Email Created

```
════════════════════════════════════════════════════════════════════════════════
🤖 AI TEMPLATE EMAIL CREATED
════════════════════════════════════════════════════════════════════════════════

📧 EMAIL DETAILS
─────────────────────────────────────────────────────────────────────────────
Status:           ✅ Created
Email ID:         12346
Subject:          🎤 CFP Alert: Submit to Speak at PyConf EU - Deadline Sept 1
Type:             AI-Generated (CFP Launch)
Link:             https://app.hubspot.com/content/emails/12346
─────────────────────────────────────────────────────────────────────────────

✅ SUCCESS! Email ready to send

🚀 NEXT STEPS:
1. Review in HubSpot
2. Make final adjustments
3. Set up send list and schedule
4. Send to your audience
════════════════════════════════════════════════════════════════════════════════
```

---

## Technical Implementation

### Backend Changes

#### State Management
- `session.meta["ai_template_generated"]` - Stores generated email data
- `session.meta["ai_template_approved"]` - Flag for approval status

#### Flow in `content_turn_ai_template()`

```python
# 1. Generate email
variant_b_data = generate_ai_content.generate_variation_b_email(...)

# 2. Store in session
session.meta["ai_template_generated"] = variant_b_data

# 3. Check if approved
is_clone_request = session.meta.get("ai_template_approved", False)

if not is_clone_request:
    # Show preview, wait for approval
    return preview_output
else:
    # Proceed with cloning
    return clone_and_complete()
```

#### Flow in `chat_turn()`

```python
# Check if user is in preview mode
is_preview_mode = bool(ai_template_generated) and not ai_template_approved

if is_preview_mode and email_approach == "ai_template":
    if "create" in message:
        # User approved
        session.meta["ai_template_approved"] = True
        return content_turn_ai_template(session)  # Proceed with clone
    
    elif "refine" in message:
        # User wants changes
        return discuss_refinements()
```

### Session States

**State 1: Preview Mode**
- `ai_template_generated`: ✓ (has data)
- `ai_template_approved`: ✗ (False)
- Action: Show preview, wait for input

**State 2: Approved**
- `ai_template_generated`: ✓ (has data)
- `ai_template_approved`: ✓ (True)
- Action: Clone to HubSpot

**State 3: Complete**
- `ai_template_generated`: ✓ (kept for reference)
- `ai_template_approved`: ✗ (reset to False)
- Action: Show final email ID

---

## User Interactions

### Scenario 1: User Approves Immediately

```
System: [Shows preview]

User: "create"

System: [Clones to HubSpot]
        [Shows email ID]
```

### Scenario 2: User Wants Refinements

```
System: [Shows preview]

User: "refine - make the subject more exciting"

System: [Discusses and potentially regenerates]
        [Shows updated preview]

User: "yes"

System: [Clones final version to HubSpot]
```

### Scenario 3: User Rejects

```
System: [Shows preview]

User: "no, start over with user content approach"

System: [Resets session]
        [Returns to approach selection or Step 1]
```

---

## Benefits

### For Users
✅ **See Before You Commit** - Review email before it's cloned  
✅ **Make Adjustments** - Request refinements before approval  
✅ **Control Quality** - Ensure email meets expectations  
✅ **Faster Still** - Preview + approval is 2-3 minutes total  
✅ **No Surprises** - Know exactly what will be sent  

### For System
✅ **Better UX** - Users feel in control  
✅ **Fewer Revisions** - Approve upfront vs edit in HubSpot  
✅ **Quality Gate** - Approval step ensures quality  
✅ **Flexible** - Can handle refine requests  
✅ **Consistent** - Same pattern as content approach  

---

## API Changes

### No Frontend Changes Needed
- Preview is shown through existing chat interface
- Approval is through chat message (no new UI components)
- Works with existing Implementation phase UI

### Backend API
- Same `/api/chat` endpoint
- `email_approach` field already in place
- Session state tracking built in

---

## Testing Checklist

- [ ] Select AI template approach in Step 2
- [ ] Proceed through Steps 3-4
- [ ] System generates email
- [ ] Preview displayed with subject, preview text
- [ ] Full email HTML preview shown
- [ ] Prompt asks for "create" or "refine"
- [ ] Reply "create" → Email cloned to HubSpot
- [ ] Email ID shown in final output
- [ ] Email appears in HubSpot draft
- [ ] Reply "refine" → Claude discusses adjustments
- [ ] After "refine", can reply "yes" to proceed
- [ ] Can switch approaches mid-flow (if not yet approved)

---

## Example Interactions

### Example 1: Quick Approval
```
System: 🤖 AI-GENERATED EMAIL PREVIEW
        Campaign Stage: CFP Launch
        Subject: 🎤 CFP Alert: Submit to Speak...
        
        ✅ APPROVE & CREATE
        Reply with 'create' or 'yes' to clone this email

User:   yes

System: [Clones to HubSpot]
        ✅ EMAIL CREATED
        Email ID: 12346
```

### Example 2: Request Refinement
```
System: 🤖 AI-GENERATED EMAIL PREVIEW
        Subject: 🎤 CFP Alert: Submit to Speak...
        
        ✅ APPROVE & CREATE

User:   refine - make the tone more casual and friendly

System: Great! I can make the email more casual and approachable.
        This would involve:
        - Changing formal language to conversational
        - Using more personal pronouns
        - Adding emojis strategically
        - Making CTAs feel less pushy
        
        Would you like me to regenerate with these changes?

User:   yes

System: [Regenerates with adjustments]
        [Shows new preview]
        
        Updated Subject: Join Our Speaker Lineup! 🎤
        ...
        
        Ready to create?

User:   create

System: [Clones final version]
        ✅ EMAIL CREATED
        Email ID: 12346
```

---

## Comparison with User Content Approach

### User Content Approach
- Show full email preview automatically
- Show refinement interface
- Auto-proceed to cloning when ready

### AI Template Approach
- Generate email
- Show preview
- Wait for approval
- Clone on approval
- OR discuss refinements

**Key Difference**: AI template requires explicit user approval, giving users control.

---

## Summary

✅ **Preview Before Cloning** - Users see exactly what's being created  
✅ **Approval Step** - User must confirm before HubSpot clone  
✅ **Refinement Option** - Can request adjustments if needed  
✅ **Same Speed** - Still 2-3 minutes total (preview + approval)  
✅ **Better UX** - Users feel informed and in control  

The AI template approach now matches the quality and control of the user content approach while maintaining its speed advantage!
