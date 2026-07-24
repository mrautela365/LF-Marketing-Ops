# Email Creation Approaches - User Content vs AI Template

## Overview

Users can now choose how they want to create their email:
1. **User Content Approach** - Provide your own copy, AI optimizes it
2. **AI Template Approach** - AI generates from best practices, no content input needed

## How It Works

### Step 1: Plan Phase
User provides event URL, system analyzes and creates campaign plan.

### Step 2: Plan Review - NEW CHOICE
After reviewing the plan, user selects their preferred approach:

```
════════════════════════════════════════════════════════════════════════════════
📧 How would you like to create this email?
════════════════════════════════════════════════════════════════════════════════

┌─────────────────────────────────────┬─────────────────────────────────────┐
│ 📝 Your Content                     │ 🤖 AI Template                      │
├─────────────────────────────────────┼─────────────────────────────────────┤
│ You provide email copy. AI analyzes │ AI generates from best practices.   │
│ and optimizes it.                   │ No content input needed.            │
│                                     │                                     │
│ ✓ Full control                      │ ✓ Auto-generated                    │
│ ✓ Your messaging                    │ ✓ Best practices                    │
│ ✓ AI optimization                   │ ✓ Fast creation                     │
└─────────────────────────────────────┴─────────────────────────────────────┘
```

### Step 3: Audience Preview
Select audience list (same for both approaches).

---

## Approach 1: User Content (Default)

### Flow
```
User provides content
    ↓
Agent creates email (Variant A)
    ↓
AI analyzes & optimizes
    ↓
AI generates Variant B from template
    ↓
Both variants ready for A/B testing
```

### What Happens
1. **User Input Required**: Yes - provide email copy/content
2. **Variant A**: Generated from user-provided content, analyzed & optimized
3. **Variant B**: Auto-generated from AI template based on campaign stage
4. **Output**: Both variants ready for A/B testing

### When to Use
- ✅ You have specific messaging you want to test
- ✅ You want AI to optimize your existing copy
- ✅ You plan to A/B test two different approaches
- ✅ You want full control over Variant A messaging

### Example Output
```
📧 A/B TESTING SETUP RESULT

VARIATION A (User Content)          VARIATION B (AI-Generated Template)
─────────────────────────────────────────────────────────────────────────
Status: ✅ Created                  Status: ✅ Created
Email ID: 12345                     Email ID: 12346
Subject: [Your subject]             Subject: 🎤 CFP Alert: Submit to Speak

Ready for A/B testing in HubSpot
```

---

## Approach 2: AI Template (New!)

### Flow
```
No user input needed
    ↓
AI generates email from best-practice template
    ↓
PREVIEW shown to user
    ↓
User approves ("yes", "create") or refines ("refine")
    ↓
Email cloned to HubSpot
    ↓
Single email ready to send
```

### What Happens
1. **User Input Required**: No - system generates everything
2. **Preview Shown**: Subject, preview text, and full email preview displayed
3. **User Approval**: User reviews and approves or requests refinements
4. **Email Generated**: Based on campaign stage (CFP Launch, Schedule Announcement, etc.)
5. **Quality**: Based on industry best practices
6. **Output**: Single optimized email ready to send or A/B test

### When to Use
- ✅ You want the fastest email creation
- ✅ You trust AI-generated content
- ✅ You don't have copy ready yet
- ✅ You want to test AI-generated approach against other variants
- ✅ You want a starting point to edit

### Example Output - Preview Stage
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

[Full email preview would be shown in HTML iframe]

✅ APPROVE & CREATE
Reply with 'create' or 'yes' to clone this email to HubSpot
Reply with 'refine' or describe changes to regenerate with adjustments

💡 TIP: You can ask me to adjust the tone, add specific details, or change the focus
════════════════════════════════════════════════════════════════════════════════
```

### Example Output - After Approval
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
1. Review in HubSpot (link above)
2. Make final adjustments if needed
3. Set up send list and schedule
4. Send to your audience

💡 TIP: Want A/B testing? Create another variant using user content approach
════════════════════════════════════════════════════════════════════════════════
```

---

## Comparison

| Aspect | User Content | AI Template |
|--------|--------------|-------------|
| **User Input** | Content required | None required |
| **Preview** | Yes (shown automatically) | Yes (shown before cloning) |
| **Approval Step** | Auto-proceed | "yes" or "create" to approve |
| **Time to Create** | 5-10 minutes | 2-3 minutes (incl. approval) |
| **Output** | 2 variants (A/B test ready) | 1 variant |
| **Customization** | Full control | AI-generated, can refine |
| **Best For** | A/B testing, custom messaging | Speed, baseline, starting point |
| **AI Usage** | Optimization | Generation + Optimization |
| **When Used** | Always available | Always available |

---

## Technical Details

### Frontend Changes
1. **Step 2 (Plan Review)**: Added choice cards showing both approaches
2. **JavaScript**: `selectApproach(approach)` function stores choice
3. **Session Storage**: Approach stored as `emailApproach`
4. **API**: Approach sent in chat messages to backend

### Backend Changes
1. **Models**: Added `email_approach` field to `ChatRequest`
2. **Main.py**: Chat endpoint stores approach in session metadata
3. **Agent.py**: 
   - `content_turn()` routes to appropriate handler based on approach
   - `content_turn_ai_template()` handles AI template approach
   - Existing `content_turn()` handles user content approach

### Data Flow
```
Frontend (selectApproach)
    ↓
Store in sessionStorage
    ↓
Include in sendChat() API call
    ↓
Backend receives email_approach
    ↓
Store in session.meta["email_approach"]
    ↓
Route to appropriate handler
    ↓
Generate email(s) based on approach
    ↓
Return appropriate output format
```

---

## User Experience

### Step 2 Choice Cards
- **Visual Design**: Two side-by-side cards with gradient on selection
- **Feedback**: Selected card highlights in blue with light background
- **Instant**: Changes take effect immediately
- **Reversible**: Can select other approach before proceeding

### Content Visibility
- **User Content Approach**: Shows "Email Content" and "Refine Content" cards
- **AI Template Approach**: Hides content input (no user input needed)

### Output Format Differences
- **User Content**: Shows both Variant A and B, side-by-side comparison
- **AI Template**: Shows single email with next steps to edit/send

---

## Implementation Details

### Choosing an Approach
1. User reviews campaign plan in Step 2
2. Sees choice cards: "Your Content" vs "AI Template"
3. Clicks desired option
4. Card highlights to show selection
5. Content sections update accordingly
6. Proceeds to Audience selection (Step 3)

### Creating with Selected Approach

**User Content Approach:**
1. User provides content in Implementation phase
2. Agent generates email from content
3. System analyzes and optimizes
4. System generates Variant B
5. Both emails cloned to HubSpot
6. User creates A/B test in HubSpot UI

**AI Template Approach:**
1. No content input needed
2. System generates email from AI template
3. Email cloned to HubSpot
4. User can edit or send directly
5. Optional: Create second variant with user content approach

---

## Code Examples

### Frontend - Selecting Approach
```javascript
function selectApproach(approach) {
  sessionStorage.setItem("emailApproach", approach);
  // Update visual feedback on selected card
  // Show/hide content input fields
}
```

### Frontend - Sending with Approach
```javascript
const emailApproach = sessionStorage.getItem("emailApproach") || "user_content";
const resp = await fetch(`${API}/chat`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    session_id: sessionId,
    message: msg,
    email_approach: emailApproach  // Pass approach
  })
});
```

### Backend - Routing
```python
email_approach = session.meta.get("email_approach", "user_content")

if email_approach == "ai_template":
    return content_turn_ai_template(session)
else:
    # Existing user content flow
    return content_turn(session, content_input)
```

---

## Testing Checklist

- [ ] Click "Your Content" button in Step 2
  - [ ] Button highlights in blue
  - [ ] Content input fields appear
  - [ ] Can proceed to Step 3
  
- [ ] Click "AI Template" button in Step 2
  - [ ] Button highlights in blue
  - [ ] Content input fields hidden
  - [ ] Can proceed to Step 3
  
- [ ] User Content Approach (Full Flow)
  - [ ] Proceed through Steps 3-4
  - [ ] Provide content in Implementation
  - [ ] Both Variant A and B created
  - [ ] Output shows both variants
  
- [ ] AI Template Approach (Full Flow)
  - [ ] Proceed through Steps 3-4
  - [ ] No content input needed
  - [ ] Single email generated
  - [ ] Output shows next steps

---

## Files Modified

1. **`frontend/index.html`**
   - Added choice cards in Step 2 (Plan Review)
   - Styled with two options side-by-side

2. **`frontend/app.js`**
   - Added `selectApproach()` function
   - Modified `sendChat()` to include email_approach
   - Added visual feedback for selection

3. **`backend/models.py`**
   - Added `email_approach` field to `ChatRequest`

4. **`backend/main.py`**
   - Updated chat endpoint to store approach in session

5. **`backend/agent.py`**
   - Modified `content_turn()` to route based on approach
   - Added `content_turn_ai_template()` for AI-first approach

---

## Future Enhancements

1. **Hybrid Approach**: Allow users to switch approaches mid-flow
2. **Template Selection**: Let users choose specific template for AI approach
3. **A/B Prediction**: Predict which variant will win based on approach
4. **Analytics**: Track performance of both approaches
5. **Comparison View**: Side-by-side compare both approaches
6. **Auto-Switching**: Suggest approach based on campaign type

---

## Summary

✅ **Choice at Decision Point** - Users select in Step 2 (Plan Review)  
✅ **Two Distinct Flows** - User Content and AI Template both fully implemented  
✅ **Visual Feedback** - Clear selection indication on choice cards  
✅ **Different Outputs** - Appropriate format for each approach  
✅ **Seamless Integration** - Works with existing A/B testing workflow  

Users now have the power to choose: provide their own copy or let AI generate it. Both approaches are optimized, fast, and ready for production.
