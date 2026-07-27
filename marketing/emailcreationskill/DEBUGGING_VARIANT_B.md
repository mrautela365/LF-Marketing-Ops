# Debugging Variant B Generation

## What Changed

I updated the `content_turn()` function with **detailed logging** so you can see exactly where Variant B generation fails or succeeds.

### Logging Points Added

Each step now logs with ✅ or ❌:

```
[CONTENT] Starting Variant B generation...
[CONTENT] ✅ generate_ai_content module loaded                     ← Import works?
[CONTENT] Event data: {...}                                       ← Data prepared?
[CONTENT] ✅ Detected stage: CFP Launch                           ← Stage detection works?
[CONTENT] Calling generate_variation_b_email(CFP Launch, ...)     ← Claude call?
[CONTENT] ✅ AI generation complete. Keys: [...]                 ← Content generated?
[CONTENT] Cloning email: 12345 → Campaign - VariantB             ← Clone source exists?
[CONTENT] ✅ Cloned Variant B email: 12346                        ← Clone succeeded?
[CONTENT] Updating Variant B settings: subject='🎤 CFP ALERT...'  ← Settings update?
[CONTENT] ✅ Updated Variant B settings                           ← Settings OK?
[CONTENT] Updating Variant B content (6254 chars)                 ← Content ready?
[CONTENT] ✅ Updated Variant B content                            ← Content OK?
[CONTENT] ✅ Variant B creation complete: 12346                   ← Final success?
```

---

## If Variant B Still Doesn't Appear

### Step 1: Check Server Logs

Look for lines starting with `[CONTENT]`:

```bash
# In your server output, search for:
grep "\[CONTENT\]" logs.txt
```

You should see:
- ✅ marks = success
- ❌ marks = failure point

### Step 2: Identify the Failure Point

#### **Failure: ❌ generate_ai_content module loaded**
```
[CONTENT] Cannot import generate_ai_content: ModuleNotFoundError
```
**Solution:** 
```python
# File must exist at: backend/generate_ai_content.py
# Verify it exists:
ls -la backend/generate_ai_content.py
```

---

#### **Failure: ❌ Detected stage: Unknown**
```
[CONTENT] ❌ Stage detection failed: ...
[CONTENT] ✅ Detected stage: Unknown
```
**Solution:** Event dates might not be parsed correctly
```python
# Check stage_detector can parse your event dates
from stage_detector import detect_stage
result = detect_stage(["2026-09-12", "2026-09-14"])
print(result)  # Should return "Event Week" or similar, not "Unknown"
```

---

#### **Failure: ❌ AI generation error**
```
[CONTENT] ❌ AI generation error: Claude API not configured
```
**Solution:** Check environment variables
```bash
# Verify ANTHROPIC_API_KEY is set
echo $ANTHROPIC_API_KEY

# In .env file:
ANTHROPIC_API_KEY=sk-ant-...
```

---

#### **Failure: ❌ No source_email_id available**
```
[CONTENT] ❌ No source_email_id available for cloning
```
**Solution:** Clone phase didn't complete
- Go back and run clone phase again
- Verify email was cloned successfully
- source_email_id should be stored in session

---

#### **Failure: ❌ Clone failed - no cloned_email_id**
```
[CONTENT] Clone result: {'error': 'Unauthorized'}
[CONTENT] ❌ Clone failed - no cloned_email_id in result
```
**Solution:** HubSpot API issue
- Check HUBSPOT_ACCESS_TOKEN is valid
- Verify source_email_id exists in HubSpot
- Check HubSpot account has email cloning permission

---

#### **Failure: ⚠️ Error updating settings**
```
[CONTENT] ⚠️ Error updating settings: HubSpot API error
```
**Solution:** Variant B is created but subject didn't update
- This is a warning, not fatal
- Email ID still exists
- You can manually edit subject in HubSpot
- But overall Variant B should still be created

---

### Step 3: Verify Both Emails Exist in HubSpot

```bash
# Check if both emails were created:
1. Go to HubSpot → Content → Emails
2. Search for: "Campaign Name - VariantB"
3. You should see:
   - Original email (Variant A)
   - Original email - VariantB (Variant B)
```

---

## Expected Output Scenarios

### **Scenario 1: ✅ SUCCESS (Both created)**
```
VARIATION A (User Content)                VARIATION B (AI-Generated Template)
─────────────────────────────────────────────────────────────────────────────
Status:           ✅ Created                      ✅ Created
Email ID:         12345                          12346
Subject:          Your subject...                🎤 CFP ALERT: Submit to Speak at...

✅ SUCCESS! Both variations ready for A/B testing
```

### **Scenario 2: ⚠️ PARTIAL (Only A created)**
```
VARIATION A (User Content)                VARIATION B (AI-Generated Template)
─────────────────────────────────────────────────────────────────────────────
Status:           ✅ Created                      ❌ Generation Failed
Email ID:         12345                          N/A

⚠️ PARTIAL: Only Variant A was created
Variant B failed to generate. Check:
  1. Claude API is configured
  2. generate_ai_content module is available
  3. Stage detection worked: [detected_stage]
```

### **Scenario 3: ❌ ERROR (Neither created)**
```
VARIATION A (User Content)                VARIATION B (AI-Generated Template)
─────────────────────────────────────────────────────────────────────────────
Status:           ❌ Missing                      ❌ Missing

❌ ERROR: Neither variant was created
Check: Agent failed to create Variant A. Review logs for details.
```

---

## Quick Debug Checklist

- [ ] Server logs show `[CONTENT]` messages with ✅ or ❌
- [ ] Check each step in order (import → stage → AI → clone → settings → content)
- [ ] First ❌ is the failure point — fix that issue
- [ ] Both emails appear in HubSpot "Content → Emails"
- [ ] Both email IDs show in the output (not "N/A")
- [ ] Can create A/B test in HubSpot with both variant IDs

---

## Example: Real Debug Output

If you provide your server output, I can identify exactly where Variant B is failing:

```
[CONTENT] Starting Variant B generation...
[CONTENT] ✅ generate_ai_content module loaded
[CONTENT] Event data: {'event_name': 'PyTorch Europe', ...}
[CONTENT] ✅ Detected stage: CFP Launch
[CONTENT] Calling generate_variation_b_email(CFP Launch, ...)
[CONTENT] ❌ AI generation error: ANTHROPIC_API_KEY not configured     ← PROBLEM HERE
```

→ **Solution:** Set ANTHROPIC_API_KEY environment variable

---

## Still Need Help?

Run the system and share:

1. **The output shown to user** (what they see in the UI)
2. **Server logs** with `[CONTENT]` lines
3. **HubSpot email list** (show both emails or just one?)

Then I can pinpoint the exact issue and fix it! 🔧
