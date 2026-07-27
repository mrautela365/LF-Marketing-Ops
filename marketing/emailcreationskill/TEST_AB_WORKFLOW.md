# Testing the A/B Workflow

## The Complete Flow (What Should Happen)

```
User Input (Event URL)
    ↓
PLAN PHASE
  - Detect event stage
  - Recommend best-practice template for Variant B
  - Output: Plan approval
    ↓
User Approves Plan
    ↓
CLONE PHASE
  - Clone source email
  - Store source_email_id in session
  - Output: Clone URL, send date input
    ↓
User Provides Content
    ↓
CONTENT PHASE ← **THIS IS WHERE VARIANT B IS CREATED**
  
  Step 1: Agent creates Variant A
    └─ Agent calls fetch_content → update_email_content
    └─ Stores variant_a_id in session.meta["email_id"]
  
  Step 2: System generates Variant B [NEW]
    ├─ Import generate_ai_content module
    ├─ Prepare event data
    ├─ Detect campaign stage
    ├─ Call Claude to generate content
    ├─ Clone source_email_id for Variant B
    ├─ Update Variant B subject & content
    └─ Store variant_b_id in session.meta
  
  Step 3: Return output with both variants
    ├─ Show Variant A ID (from session.meta["email_id"])
    ├─ Show Variant B ID (from HubSpot clone result)
    └─ Instructions for creating A/B test in HubSpot
    ↓
Output Shows BOTH Email IDs
    ↓
User Creates A/B Test in HubSpot UI
    ↓
SUCCESS ✅
```

---

## What to Check Right Now

### **1. Run the system end-to-end**

```bash
# Start the server
python backend/main.py

# Then in the UI, go through:
1. Plan phase - provide event URL
2. Clone phase - approve and provide send date
3. Content phase - provide content for Variant A
```

### **2. Check the Output**

You should see in the Content phase output:

```
════════════════════════════════════════════════════════════════════════════════
📧 A/B TESTING SETUP RESULT
════════════════════════════════════════════════════════════════════════════════

VARIATION A (User Content)                VARIATION B (AI-Generated Template)
─────────────────────────────────────────────────────────────────────────────
Status:           ✅ Created                      ✅ Created
Email ID:         12345                          12346
                  ↑                               ↑
             THIS MUST HAVE                  THIS MUST HAVE
             AN EMAIL ID                     AN EMAIL ID
```

### **3. If only Variant A shows:**

```
Status:           ✅ Created                      ❌ Generation Failed
Email ID:         12345                          N/A
```

→ **Check server logs** for `[CONTENT]` lines showing where it failed

### **4. Check HubSpot Email List**

Go to HubSpot → Content → Emails, search for your campaign:

You should see:
- `Your Campaign Name` (Variant A)
- `Your Campaign Name - VariantB` (Variant B)

If you only see one, Variant B wasn't created.

---

## Debugging Commands

### **Check if modules exist:**

```bash
ls -la backend/generate_ai_content.py    # Must exist
ls -la backend/ai_email_templates.py     # Must exist
```

### **Test stage detection:**

```python
from stage_detector import detect_stage

# Test with your event dates
result = detect_stage(["2026-09-12", "2026-09-14"])
print(f"Stage detected: {result}")
# Expected: "Event Week" or similar, NOT "Unknown"
```

### **Test AI content generation:**

```python
from generate_ai_content import generate_variation_b_email
from ai_email_templates import get_all_ai_templates

# Check templates exist
templates = get_all_ai_templates()
print(f"Available stages: {list(templates.keys())}")

# Test content generation
event_data = {
    "event_name": "Test Event",
    "location": "New York",
    "dates": "September 12-14, 2026",
    "key_topics": ["Python", "AI/ML"]
}

result = generate_variation_b_email("CFP Launch", event_data)
if "error" in result:
    print(f"ERROR: {result['error']}")
else:
    print(f"✅ Generated subject: {result.get('subject')}")
```

### **Check Claude API:**

```bash
# Verify ANTHROPIC_API_KEY is set
echo $ANTHROPIC_API_KEY
# Output: sk-ant-... (not empty)
```

---

## Expected Results at Each Phase

### **Phase 1: PLAN**
```
✅ You should see:
  - Event name, dates, location detected
  - Recommended best-practice template name
  - Button to approve/proceed to Clone
```

### **Phase 2: CLONE**
```
✅ You should see:
  - Source email cloned
  - Email ID displayed
  - Form to enter send date
  - "Proceed to Content" button
```

### **Phase 3: CONTENT** ← **VARIANT B CREATED HERE**
```
✅ You should see:
  
  VARIATION A (User Content)          VARIATION B (AI-Generated Template)
  ─────────────────────────────────────────────────────────────────────────
  Status: ✅ Created                  Status: ✅ Created
  Email ID: 12345                     Email ID: 12346
  
  ✅ SUCCESS! Both variations ready for A/B testing
```

---

## If Variant B Still Shows as "Generation Failed"

### Option 1: Check Server Logs

Look for lines like:
```
[CONTENT] ❌ generate_ai_content module loaded: ModuleNotFoundError
[CONTENT] ❌ AI generation error: ANTHROPIC_API_KEY not configured
[CONTENT] ❌ Clone failed - no cloned_email_id in result
```

The first ❌ line is the problem.

### Option 2: Manually Create Variant B

While we debug:
1. In HubSpot, clone Variant A email manually
2. Rename it to "Campaign Name - VariantB"
3. Change the subject (to something different from Variant A)
4. Use this as Variant B for testing

### Option 3: Run Minimal Test

```python
# Minimal test to isolate issue
import sys
sys.path.insert(0, 'backend')

try:
    from generate_ai_content import generate_variation_b_email
    print("✅ Module imported successfully")
    
    result = generate_variation_b_email("CFP Launch", {
        "event_name": "Test",
        "location": "NYC",
        "dates": "Sept 12-14"
    })
    
    if "error" in result:
        print(f"❌ Generation failed: {result['error']}")
    else:
        print(f"✅ Generated content")
        print(f"   Subject: {result.get('subject')}")
        print(f"   HTML length: {len(result.get('html', ''))}")
        
except ImportError as e:
    print(f"❌ Cannot import module: {e}")
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
```

---

## Final Checklist

- [ ] Both `generate_ai_content.py` and `ai_email_templates.py` exist
- [ ] `ANTHROPIC_API_KEY` environment variable is set
- [ ] Server logs show `[CONTENT] ✅` marks (not ❌)
- [ ] Output shows **TWO** email IDs (not N/A for Variant B)
- [ ] Both emails appear in HubSpot email list
- [ ] Can create A/B test with both variant IDs

Once all these pass, you'll see Variant B! ✅
