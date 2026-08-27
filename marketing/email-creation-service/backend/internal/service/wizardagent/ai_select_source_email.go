package wizardagent

import (
	"context"
	"fmt"
	"strings"
)

// SourceEmailCandidate is one entry of the candidates list passed to
// AISelectSourceEmail.
type SourceEmailCandidate struct {
	EmailID     string
	Name        string
	PublishDate string
}

// AISelectSourceEmail ports ai_select_source_email — an LLM-driven pick of
// the best-matching past-campaign email to use as the clone source, out of
// a short candidate list already narrowed by SearchEmailsForEvent/
// GetBrandEmails. Returns ("", false) immediately if candidates is empty,
// and after exhausting maxAttempts without a CONFIDENT: YES answer —
// exactly like Python returning None in both cases.
func (a *Agent) AISelectSourceEmail(ctx context.Context, eventName, eventShortName, location string, candidates []SourceEmailCandidate, url string, maxAttempts int) (string, bool) {
	if len(candidates) == 0 {
		return "", false
	}
	if maxAttempts <= 0 {
		maxAttempts = 5
	}

	rejectionHint := ""
	for attempt := 0; attempt < maxAttempts; attempt++ {
		prompt := buildSourceSelectionPrompt(eventName, eventShortName, location, candidates, url, rejectionHint)

		text, err := a.claudeText(ctx, prompt, 150, 60, 0)
		if err != nil {
			// Ports the per-attempt try/except that swallows the error and
			// retries.
			continue
		}

		selID, confident := parseSelectAnswer(text)
		if selID == "" {
			rejectionHint = "⚠️  Your previous response did not contain a SELECT: line.\nFollow the 3-line format exactly.\n\n"
			continue
		}

		var matchedName string
		valid := false
		for _, c := range candidates {
			if c.EmailID == selID {
				valid = true
				matchedName = c.Name
				break
			}
		}
		if !valid {
			rejectionHint = fmt.Sprintf("⚠️  ID %s does not appear in the candidate list above.\nChoose an ID exactly as shown.\n\n", selID)
			continue
		}

		if confident {
			return selID, true
		}

		firstLocation := location
		if idx := strings.Index(location, ","); idx >= 0 {
			firstLocation = location[:idx]
		}
		rejectionHint = fmt.Sprintf(
			"⚠️  Attempt %d: you selected %q but marked CONFIDENT: NO.\nRe-examine the list focusing on %q and %q.\n\n",
			attempt+1, matchedName, firstLocation, eventShortName,
		)
	}

	return "", false
}

func buildSourceSelectionPrompt(eventName, eventShortName, location string, candidates []SourceEmailCandidate, url, rejectionHint string) string {
	firstLocation := location
	if idx := strings.Index(location, ","); idx >= 0 {
		firstLocation = location[:idx]
	}

	var lines []string
	for _, c := range candidates {
		name := c.Name
		if name == "" {
			name = "(no name)"
		}
		lines = append(lines, fmt.Sprintf("  ID: %s  |  %s  |  sent: %s", c.EmailID, name, c.PublishDate))
	}
	emailList := strings.Join(lines, "\n")

	urlLine := ""
	if url != "" {
		urlLine = fmt.Sprintf("Event URL  : %s\n", url)
	}

	var b strings.Builder
	b.WriteString("You are a marketing operations specialist selecting the best HubSpot email\n")
	b.WriteString("template to clone for a new event campaign.\n\n")
	b.WriteString("━━━ NEW EVENT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
	fmt.Fprintf(&b, "Event Name : %s\n", eventName)
	fmt.Fprintf(&b, "Short Name : %s\n", eventShortName)
	fmt.Fprintf(&b, "Location   : %s\n", location)
	b.WriteString(urlLine)
	b.WriteString("\n")
	b.WriteString("━━━ CANDIDATE EMAILS (sent emails for this brand, newest first) ━━━━━━━━━━━\n")
	fmt.Fprintf(&b, "%s\n\n", emailList)
	b.WriteString(rejectionHint)
	b.WriteString("━━━ SELECTION RULES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
	b.WriteString("PRIORITY 1 — EXACT MATCH (preferred):\n")
	fmt.Fprintf(&b, "  Same event series + same city/region → look for '%s' in the name.\n\n", firstLocation)
	b.WriteString("PRIORITY 2 — SERIES MATCH:\n")
	fmt.Fprintf(&b, "  Same event series, any location → look for '%s' or key words\n", eventShortName)
	fmt.Fprintf(&b, "  from '%s' in the name.\n\n", eventName)
	b.WriteString("PRIORITY 3 — BRAND MATCH (last resort):\n")
	b.WriteString("  Same brand, most recently sent — only if no series match exists.\n\n")
	b.WriteString("CRITICAL RULES:\n")
	b.WriteString("  • NEVER pick an email from a different region when a location-specific\n")
	fmt.Fprintf(&b, "    email exists (e.g. do NOT pick 'North America' if '%s' is available).\n", firstLocation)
	b.WriteString("  • Prefer the most recent edition of the matched series.\n")
	b.WriteString("  • A 'Last Chance' or 'Save the Date' email for the correct event is\n")
	b.WriteString("    better than an 'Invite' for the wrong location.\n")
	b.WriteString("  • Match on event series keywords: ignore generic words like 'summit',\n")
	b.WriteString("    'conference', 'register', 'join', 'meet'.\n\n")
	b.WriteString("━━━ YOUR ANSWER ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
	b.WriteString("Reply in EXACTLY this format (3 lines, nothing else):\n")
	b.WriteString("SELECT: <email_id>\n")
	b.WriteString("CONFIDENT: YES or NO\n")
	b.WriteString("REASON: <one sentence explaining priority tier used and why>")
	return b.String()
}

// parseSelectAnswer parses the SELECT:/CONFIDENT:/REASON: 3-line answer
// format exactly as ai_select_source_email does: SELECT: takes only the
// first whitespace-delimited token after the colon (tolerating trailing
// annotation text), and CONFIDENT: is a case-insensitive substring match
// for "YES" rather than an exact-equality check.
func parseSelectAnswer(text string) (selID string, confident bool) {
	for _, line := range strings.Split(text, "\n") {
		ls := strings.TrimSpace(line)
		upper := strings.ToUpper(ls)
		if strings.HasPrefix(upper, "SELECT:") {
			rest := strings.TrimSpace(ls[len("SELECT:"):])
			fields := strings.Fields(rest)
			if len(fields) > 0 {
				selID = fields[0]
			}
		}
		if strings.HasPrefix(upper, "CONFIDENT:") {
			confident = strings.Contains(upper[len("CONFIDENT:"):], "YES")
		}
	}
	return selID, confident
}
