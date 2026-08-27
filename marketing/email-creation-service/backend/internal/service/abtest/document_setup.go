// Package abtest ports integrations/hubspot.py's document_ab_test_setup —
// HubSpot has no API for creating A/B tests on marketing emails, so this
// only generates manual setup instructions for the HubSpot UI.
package abtest

import (
	"fmt"
	"strings"
)

// Variant describes one side of an A/B test.
type Variant struct {
	EmailID       string
	Subject       string
	Type          string
	TemplateKey   string // Variant B only
	QualityRating int    // Variant B only, 1-5
	RatingDisplay string // Variant B only, e.g. "★★★★☆"
}

// Setup is the result of DocumentABTestSetup.
type Setup struct {
	ReadyForABTest bool
	VariantA       Variant
	VariantB       Variant
	Instructions   string
}

// DocumentABTestSetup ports document_ab_test_setup verbatim.
func DocumentABTestSetup(variantAID, variantASubject, variantBID, variantBSubject, templateKey string, qualityRating int) Setup {
	starRating := strings.Repeat("★", qualityRating) + strings.Repeat("☆", 5-qualityRating)

	instructions := fmt.Sprintf(`
🎯 A/B TEST SETUP — MANUAL STEPS IN HUBSPOT UI

Both variants are ready in HubSpot as DRAFT emails. Follow these steps to create the A/B test:

1. GO TO HUBSPOT
   → Campaigns → [Event Name] → Settings

2. SCROLL TO "A/B Test" SECTION
   → Click "Create A/B Test" or "Add A/B Test"

3. CONFIGURE VARIANT A (Control)
   Email ID: %s
   Name: Variant A (User Content)
   Subject: %s

4. CONFIGURE VARIANT B (Treatment)
   Email ID: %s
   Name: Variant B (%s)
   Subject: %s

5. SET TEST PARAMETERS
   Split: 50/50 (50%% get Variant A, 50%% get Variant B)
   Test Variable: Subject Line (Recommended)
   Duration: 24-48 hours minimum
   Auto-select Winner: Yes (recommended)

6. SEND TEST
   Click "Send A/B Test"

7. MONITOR RESULTS
   Track: Open Rate, Click-Through Rate, Conversions
   Compare: Which variant performs better?

EXPECTED OUTCOMES (from ArgoCon data):
  Variant A: Unknown (user content)
  Variant B: %s (%d/5 stars) - %d%% open rate expected

NOTES:
  • HubSpot requires both emails to use the same template type
  • A/B test results are available in Campaign Analytics after send
  • Consider repeating with different test variables (send time, sender, etc.)
  • Document winning variant for future campaign templates
`,
		variantAID, variantASubject,
		variantBID, templateKey, variantBSubject,
		starRating, qualityRating, qualityRating*10,
	)

	return Setup{
		ReadyForABTest: true,
		VariantA: Variant{
			EmailID: variantAID,
			Subject: variantASubject,
			Type:    "User-Created Content",
		},
		VariantB: Variant{
			EmailID:       variantBID,
			Subject:       variantBSubject,
			Type:          "Best-Practice Template",
			TemplateKey:   templateKey,
			QualityRating: qualityRating,
			RatingDisplay: starRating,
		},
		Instructions: instructions,
	}
}
