# Variation A - AI-Powered Content Analysis & Optimization

## Overview

Variation A emails are now automatically analyzed and optimized using Claude AI. The system evaluates email quality across multiple dimensions and applies improvements automatically if score is below 8/10.

## What Gets Analyzed

When Variation A is created, Claude AI analyzes:

### 1. **Subject Line** (1-10 score)
- Length effectiveness (recommended: under 60 chars)
- Use of power words and urgency
- Clarity and benefit-focused messaging
- Spam trigger words
- Emoji usage appropriateness

### 2. **Call-to-Action (CTA)**
- Clarity and directness (1-10)
- Placement and visibility
- Number of CTAs (too many confuses recipients)
- Urgency level alignment with campaign
- Button text effectiveness

### 3. **Tone**
- Current tone (formal, casual, urgent, friendly, etc.)
- Appropriateness for target audience
- Consistency with event type
- Emotional appeal

### 4. **Engagement**
- Opening hook strength (1-10) - does it grab attention?
- Personalization level (none/basic/strong)
- Emotional appeal score (1-10)
- Reader motivation

### 5. **Formatting**
- Readability score (1-10)
- Visual hierarchy and scanning ability
- Mobile-friendliness
- Whitespace and padding

### 6. **Personalization**
- Current personalization approach
- Missed opportunities for personalization
- Segment-specific messaging gaps

## How It Works

### Flow Diagram

```
User provides content for Variation A
    ↓
Agent generates email with Claude
    ↓
Email updated in HubSpot
    ↓
[NEW] AI Analysis Phase:
  1. Fetch email from HubSpot
  2. Run Claude analysis (all 6 dimensions)
  3. Generate 3-5 improvement suggestions
  4. Calculate quality score (0-10)
  5. If score < 8: Apply improvements automatically
     - Update subject line
     - Optimize CTA
     - Improve formatting
     - Enhance copy
  6. If score >= 8: Keep original
    ↓
Both emails (Variant A optimized + Variant B) shown to user
    ↓
User reviews A/B test setup
```

## Output Format

### Analysis Report Shown to User

```
════════════════════════════════════════════════════════════════════════════════
🔍 VARIATION A - AI CONTENT ANALYSIS & OPTIMIZATION
════════════════════════════════════════════════════════════════════════════════

🟢 Email Quality Score: 8.5/10

📝 Summary:
Your email has a strong opening and clear CTA, but the subject line could be 
more benefit-focused. Consider highlighting the unique value proposition earlier.

✅ IMPROVEMENTS APPLIED:
1. Subject Line
   Issue: Generic opening, lacks urgency
   Recommendation: Add power word and event value
   Impact: Higher open rates (est. +5-10%)

2. CTA Button
   Issue: Secondary CTA buried in footer
   Recommendation: Move primary CTA higher, remove secondary
   Impact: Higher CTR (est. +3-7%)

3. Formatting
   Issue: Long paragraphs without breaks
   Recommendation: Add subheadings and bullet points
   Impact: Better scannability and engagement

📌 Key Change:
   Original: Join Us at PyConf Europe 2026
   Improved: 🎤 Become a Speaker at PyConf Europe - Deadline Sept 1
```

## Improvement Categories

### Subject Line Improvements
- Add power words: "Discover", "Unlock", "Transform", "Don't miss", "Limited time"
- Include benefit/value: "Get 50% off", "Free training included"
- Create curiosity: "What if...", "Revealed...", "Secret..."
- Emoji usage: Relevant emojis increase opens (test needed)
- Length optimization: 35-50 characters performs best

### CTA Improvements
- Primary CTA should appear 2-3 times
- Use benefit-focused text: "Claim my seat" instead of "Register"
- Add urgency: "Register now - limited spots"
- Place above the fold (first CTA should be near top)
- Use contrasting button colors
- Clear secondary actions

### Tone Improvements
- Match event urgency (CFP Launch = high urgency)
- Align with audience (corporate vs startup)
- Balance professionalism with friendliness
- Use "you" language instead of "we"
- Tell a story, not just facts

### Engagement Improvements
- Hook readers in first 2 lines
- Lead with benefit, not features
- Create fear of missing out (FOMO) when appropriate
- Show social proof (attendee count, speaker quality)
- Highlight unique aspects of event

### Formatting Improvements
- Single column for mobile optimization
- Max 80 characters per line
- Subheadings every 3-4 lines
- Bullet points instead of long paragraphs
- Images with alt text
- White space between sections

### Personalization Improvements
- Use recipient name (if available)
- Segment by interest (pydata vs infra)
- Tailor language (first-timer vs returning attendee)
- Customize CTAs by persona
- Reference past attendance

## Quality Score Interpretation

| Score | Meaning | Action |
|-------|---------|--------|
| 9-10 | Excellent | No changes needed |
| 8-8.9 | Very Good | Minor improvements only if < 8 |
| 7-7.9 | Good | Should optimize |
| 6-6.9 | Fair | Needs improvements |
| Below 6 | Poor | Major rewrites recommended |

## When Improvements Are Applied

Improvements are automatically applied when:
1. Analysis score is **below 8/10**, AND
2. AI generates improved versions of:
   - Subject line, OR
   - Preview text, OR
   - Email body HTML

If all scores are 8+, original email is kept unchanged.

## Files Involved

| File | Role |
|------|------|
| `analyze_email_content.py` | NEW - Core analysis and optimization module |
| `agent.py` | MODIFIED - Integrates analysis into content_turn() |
| `hubspot_tools.py` | MODIFIED - Added get_email_details() function |

## Key Functions

### `analyze_email_content.py`

```python
analyze_and_improve_email(
    email_subject: str,
    email_body: str,
    email_preview: str,
    event_data: Dict[str, Any],
    event_type: str
) -> Dict[str, Any]
```

Returns analysis with:
- `overall_score`: 0-10 quality score
- `analysis`: Dict with scores for each dimension
- `improvements`: List of specific improvements
- `improved_email`: Optimized versions (subject, preview, body)
- `summary`: 2-3 sentence summary

### `optimize_subject_line(subject: str, event_type: str)`
Generates 3-5 subject line variants with strategies.

### `generate_cta_variants(current_cta_text: str, goal: str, urgency: str)`
Generates optimized CTA button text variants.

## Configuration

### Environment Variables
```
ANTHROPIC_API_KEY=sk-ant-...  # Required for Claude analysis
```

### Model
- **Model**: Claude Opus 4.8 (most capable)
- **Max tokens**: 4000 (generous for detailed analysis)
- **Temperature**: 0 (deterministic results)

## Error Handling

If analysis fails:
- ✅ Email still created and sent successfully
- ⚠️ Warning logged, not fatal
- 📧 Original email preserved (no improvements applied)
- 📊 No analysis shown to user (graceful degradation)

```python
try:
    analysis = analyze_and_improve_email(...)
except Exception as e:
    _log.warning(f"Analysis failed (non-critical): {e}")
    # Continue with original email
```

## Testing

### Unit Tests
```python
# Test analysis on sample email
analysis = analyze_and_improve_email(
    subject="Join Us at PyConf Europe",
    body="<html>...",
    preview="Event happening soon",
    event_data={...},
    event_type="CFP Launch"
)

assert analysis.get("overall_score") >= 0
assert analysis.get("overall_score") <= 10
assert "improvements" in analysis
assert "improved_email" in analysis
```

### Integration Test
1. Create campaign through full flow
2. Check server logs for [CONTENT] analysis lines
3. Verify improved subject in HubSpot email draft
4. Check A/B test output shows analysis results

## Example Output

### Before (User Input)
```
Subject: Event This Fall
Body: We're hosting an event...
```

### Analysis Result
```
Score: 6.5/10
Issues:
- Subject is vague (no benefit/urgency)
- Body is passive voice ("we're hosting" vs "come discover")
- Missing social proof
- No CTA until footer
```

### After (Improvements Applied)
```
Subject: 🎤 Keynotes from 50+ Tech Leaders - Early Bird Ends Sept 1
Body: [Improved with stronger opening, moved CTA higher, added attendee count, etc.]
```

## Metrics Impact

Expected improvements when applying analysis:
- **Subject Line**: +5-10% open rate
- **CTA Optimization**: +3-7% click-through rate
- **Formatting**: +10-15% readability
- **Overall**: +8-12% conversion rate

*Note: Actual results vary by audience and campaign type*

## Future Enhancements

1. **A/B Test Predictions**
   - Predict which variant will win
   - Confidence levels
   - Supporting metrics

2. **Recipient Segmentation**
   - Analyze how tone changes by segment
   - Personalization suggestions per segment
   - Dynamic subject lines

3. **Competitive Benchmarking**
   - Compare to similar events
   - Industry average scores
   - Top performer patterns

4. **Learning Loop**
   - Track actual performance (opens, clicks)
   - Feed back into analysis
   - Improve recommendations over time

## Troubleshooting

### Analysis Not Running
```
[CONTENT] ⚠️ Analysis phase failed (non-critical): ModuleNotFoundError
```
**Solution**: Check `analyze_email_content.py` exists in backend/

### Claude API Not Available
```
[CONTENT] ⚠️ Analysis returned error: ANTHROPIC_API_KEY not configured
```
**Solution**: Set `ANTHROPIC_API_KEY` environment variable

### Email Details Not Fetched
```
[CONTENT] ⚠️ Could not fetch Variant A details from HubSpot
```
**Solution**: Verify email_id is correct and HubSpot API access is valid

## Summary

✅ **Automated Content Analysis** - Every Variation A gets analyzed for quality
✅ **Improvement Suggestions** - Specific, actionable recommendations
✅ **Automatic Optimization** - Improvements applied if score < 8/10
✅ **Transparent Reporting** - User sees analysis and changes made
✅ **Non-Blocking** - Analysis failures don't prevent email creation
✅ **Email Marketing Best Practices** - Based on industry standards and testing

This feature ensures that every Variation A email is optimized for performance before A/B testing begins.
