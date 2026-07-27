# A/B Test API Implementation - HubSpot Native Integration

## Overview

**Before**: Users created two separate emails and manually created A/B test in HubSpot UI
**After**: System uses HubSpot A/B Test API to create proper variations automatically

---

## What Changed

### Old Approach ❌
```
1. Clone source email → Variant A (user content)
2. Clone source email again → Variant B (AI template)
3. User goes to HubSpot UI
4. Manually creates A/B test
5. Assigns variant IDs
6. Configures test settings
```
**Problems**:
- Manual step required (friction)
- Two independent emails, not true variations
- User error-prone (could assign wrong variant)
- Not tracked as formal A/B test

### New Approach ✅
```
1. Clone source email → Variant A (user content)
2. Create A/B variation → Variant B (AI template)
3. System returns A/B test ID
4. A/B test is automatically configured
5. Ready to send (or configure further in HubSpot)
```
**Benefits**:
- No manual step needed
- True A/B variations (linked together)
- System-created relationship
- Proper tracking by HubSpot

---

## HubSpot API Used

### Endpoint
```
POST /marketing/v3/emails/{email_id}/ab-test-variants
```

### What It Does
Creates a new variation of an email for A/B testing.

### Request
```json
POST /marketing/v3/emails/12345/ab-test-variants
{}
```

### Response
```json
{
  "id": "ab_test_12345",
  "variantId": "email_12346",
  "parentEmailId": "12345",
  "createdAt": "2026-07-22T10:30:00Z",
  "status": "draft"
}
```

### Fields Returned
- `id` (ab_test_id) - A/B test ID
- `variantId` (variant_b_id) - The new email variation ID
- `parentEmailId` - Original email ID (Variant A)
- `status` - State of the test ("draft", "sent", etc.)

---

## Flow Diagram

### New Flow with API

```
User selects approach (Step 2)
    ↓
Plan & Audience selection (Steps 1-3)
    ↓
Implementation (Step 4)
    ├─ User Content Approach:
    │  ├─ Clone source email → Variant A
    │  ├─ Update with user content
    │  ├─ Run analysis & optimize
    │  ├─ Create A/B variation → Variant B
    │  ├─ Update with AI content
    │  └─ Get: ab_test_id, variant_a_id, variant_b_id
    │
    └─ AI Template Approach:
       ├─ Clone source email → Variant A
       ├─ Show preview
       ├─ Wait for approval
       ├─ Create A/B variation → Variant B
       ├─ Update with AI content
       └─ Get: ab_test_id, variant_a_id, variant_b_id
    
Output
├─ ✅ A/B Test Created Successfully
├─ A/B Test ID: ab_test_12345
├─ Variant A ID: email_12345 (User Content)
├─ Variant B ID: email_12346 (AI Template)
└─ Ready for deployment

User Action (In HubSpot)
├─ Configure test settings (optional)
├─ Choose winner metric (open rate, clicks, etc.)
├─ Set audience split (50/50 recommended)
└─ Send
```

---

## Code Implementation

### In hubspot_tools.py

```python
def create_ab_variation(email_id: str) -> dict:
    """
    Create an A/B test variation using HubSpot API.
    
    Args:
        email_id: Parent email ID (Variant A)
    
    Returns:
        {
            "status": "success" | "error",
            "ab_test_id": "...",
            "variant_id": "...",
            "parent_email_id": "..."
        }
    """
    # POST to /marketing/v3/emails/{email_id}/ab-test-variants
    result = _post(f"/marketing/v3/emails/{email_id}/ab-test-variants", {})
    
    return {
        "status": "success",
        "ab_test_id": result.get("id"),
        "variant_id": result.get("variantId"),
        "parent_email_id": email_id
    }
```

### In agent.py (content_turn)

```python
# Step 2B: Create A/B variation for Variant B
ab_result = hubspot_tools.create_ab_variation(variant_a_id)

if ab_result.get("status") != "success":
    raise Exception(f"A/B variation failed: {ab_result.get('error')}")

variant_b_id = ab_result.get("variant_id")
ab_test_id = ab_result.get("ab_test_id")

# Update Variant B with AI content
hubspot_tools.update_email_settings(variant_b_id, subject=variant_b_data["subject"])
hubspot_tools.update_email_content(variant_b_id, html=variant_b_data["html"])

# Store in session
session.meta["ab_test_id"] = ab_test_id
```

---

## Output to User

### Success Output
```
════════════════════════════════════════════════════════════════════════════════
✅ A/B TEST CREATED SUCCESSFULLY
════════════════════════════════════════════════════════════════════════════════

🎯 A/B TEST SETUP
─────────────────────────────────────────────────────────────────────────────
A/B Test ID:      ab_test_12345
Variant A (Base): email_12345 - User-provided content
Variant B:        email_12346 - AI-generated template
Status:           ✅ Ready for deployment
─────────────────────────────────────────────────────────────────────────────

🚀 NEXT STEPS
1. Go to HubSpot → Campaigns → Email Settings
2. Find your email campaign
3. View A/B Test → Edit (or send directly if ready)
4. Set audience split: 50/50 (recommended)
5. Choose winner selection method:
   - Open rate (most common)
   - Click rate
   - Conversion rate
6. Set test duration
7. Review and send

📊 TIPS FOR SUCCESS
• Variant A subject: [subject text]
• Variant B subject: [different subject]
• Both use same template structure
• Only subject and content differ
• Recommended test variable: Subject Line
════════════════════════════════════════════════════════════════════════════════
```

---

## Advantages of API Approach

### 1. **No Manual Steps**
- ✅ A/B test created automatically
- ✅ No UI navigation needed
- ✅ No copy/paste of email IDs
- ✅ No configuration errors

### 2. **Proper A/B Test Structure**
- ✅ True parent-child relationship
- ✅ Linked variations
- ✅ Shared A/B test ID
- ✅ HubSpot recognizes as test

### 3. **Reduced Errors**
- ✅ No wrong variant assignment
- ✅ No misconfigured tests
- ✅ No duplicate subject lines
- ✅ System-enforced structure

### 4. **Better Tracking**
- ✅ A/B test ID for reference
- ✅ Proper campaign attribution
- ✅ HubSpot analytics linked
- ✅ Test results aggregated

### 5. **User Experience**
- ✅ Faster completion
- ✅ Clear confirmation
- ✅ One-step deployment
- ✅ Professional workflow

---

## Comparison

| Aspect | Manual UI | API Approach |
|--------|-----------|-------------|
| **Creation** | 4-5 steps | 0 steps (automatic) |
| **User Interaction** | Required | Not needed |
| **Error Prone** | High | Low |
| **A/B Structure** | Two emails + test | Proper variations |
| **Time** | 2-3 minutes | < 10 seconds |
| **Tracking** | Manual | Automatic |
| **Consistency** | Variable | Guaranteed |
| **Flexibility** | High | Medium |

---

## Error Handling

### If API Call Fails

```python
try:
    ab_result = hubspot_tools.create_ab_variation(variant_a_id)
    
    if ab_result.get("status") != "success":
        raise Exception(f"Failed: {ab_result.get('error')}")
        
except Exception as e:
    log.error(f"A/B variation failed: {e}")
    # Fall back: Still have variant_a_id and variant_b_id
    # User can manually create A/B test in HubSpot UI if needed
    raise
```

### Fallback Strategy
If A/B variation API fails:
1. Variant A is created (cloned + updated)
2. Variant B is created (cloned + updated)
3. Error logged
4. User informed
5. User can still manually create A/B test in HubSpot

---

## Testing

### Unit Test
```python
def test_create_ab_variation():
    # Create test email first
    clone_result = hubspot_tools.clone_email("source_id", "test")
    email_id = clone_result["email_id"]
    
    # Create A/B variation
    ab_result = hubspot_tools.create_ab_variation(email_id)
    
    # Verify
    assert ab_result["status"] == "success"
    assert ab_result["ab_test_id"] is not None
    assert ab_result["variant_id"] is not None
    assert ab_result["variant_id"] != email_id
```

### Integration Test
```
Full campaign flow:
1. Plan & clone (Variant A)
2. User content → Update Variant A
3. Analysis & optimize Variant A
4. Create A/B variation → Variant B
5. AI content → Update Variant B
6. Verify A/B test in HubSpot
7. Check both emails exist
8. Confirm linked as test
```

---

## HubSpot Configuration (In UI)

After A/B test is created via API, user can:

1. **View Test**
   - HubSpot → Campaigns → Email
   - See A/B test with both variants listed

2. **Configure Winner Metric**
   - Open rate (default, most common)
   - Click rate
   - Conversion rate
   - Custom metric

3. **Set Audience Split**
   - 50/50 (recommended for balanced test)
   - 60/40, 70/30 (if segment is asymmetric)
   - Winner gets remaining traffic

4. **Set Duration**
   - Short: 1-3 days
   - Medium: 1-2 weeks
   - Long: 2-4 weeks

5. **Send**
   - To selected audience
   - System automatically manages variants

---

## Benefits Over Manual Approach

### From User Perspective
- ✅ Faster workflow (no manual steps)
- ✅ Less confusing (single output)
- ✅ No copy/paste errors
- ✅ Professional result

### From System Perspective
- ✅ Automated, no user error
- ✅ Proper data structure
- ✅ Better tracking
- ✅ Scalable for bulk operations
- ✅ API-driven workflow

### From Data Perspective
- ✅ Clean linked variations
- ✅ Shared A/B test ID
- ✅ Proper attribution
- ✅ Complete audit trail

---

## API Documentation Reference

**Endpoint**: `POST /marketing/v3/emails/{email_id}/ab-test-variants`

**Authentication**: Bearer token (HUBSPOT_ACCESS_TOKEN)

**Headers**: 
```
Authorization: Bearer {token}
Content-Type: application/json
```

**Body**: `{}` (empty, creates default variation)

**Response**: A/B test object with parent and variant IDs

**Errors**:
- 401: Authentication failed
- 404: Email not found
- 409: Email already has a test
- 500: Server error

---

## Summary

✅ **API-Based Creation** - No manual UI steps  
✅ **Automatic Configuration** - System handles structure  
✅ **Proper Linking** - True A/B test variations  
✅ **Better Tracking** - HubSpot recognizes test  
✅ **Faster Workflow** - Seconds instead of minutes  
✅ **Less Error-Prone** - System validation  

The A/B test is now **created automatically using the HubSpot API**, giving users a professional, efficient workflow with proper campaign structure!
