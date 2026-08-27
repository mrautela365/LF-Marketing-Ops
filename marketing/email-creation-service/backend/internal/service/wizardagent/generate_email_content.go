package wizardagent

import (
	"context"
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strings"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/emailtemplates"
)

// GenerateEmailContentInput bundles generate_email_content's argument list.
type GenerateEmailContentInput struct {
	EventDetails  model.ScrapedEventFull
	Stage         StageInput
	BrandHistory  map[string]any
	ChangeRequest string
	SourceEmailID string
	ReferenceIDs  []string
}

// StageInput carries the subset of stagedetector.Result generate_email_content
// reads (stage_info in Python: name, funnel, cta_label, event_date_str,
// marketing_strategy, content_ideas, stage_number).
type StageInput struct {
	Name              string
	Funnel            string
	CTALabel          string
	EventDateStr      string
	DaysToEvent       *int
	MarketingStrategy string
	ContentIdeas      []string
	StageNumber       *int
}

// referenceEmail is one candidate reference read via GetEmailContentText,
// paired with its computed richness (rich_text section count) — ports the
// refs_read list built before picking the richest as the primary reference.
type referenceEmail struct {
	Content  *model.EmailContentText
	Richness int
}

func richness(c *model.EmailContentText) int {
	n := 0
	for _, s := range c.Sections {
		if s.Type == "rich_text" {
			n++
		}
	}
	return n
}

var stripTagsRe = regexp.MustCompile(`<[^>]+>`)
var collapseWhitespaceRe = regexp.MustCompile(`\s+`)

// GenerateEmailContent ports generate_email_content — Variant B's
// reference-driven content generator. Reads up to 3 ranked past-campaign
// emails' actual HTML, picks the richest as the structural template, learns
// house style/tone from all of them, then has the LLM produce
// structurally-similar new content for the current event. Falls back to
// emailtemplates.GetTemplate(stageName) when no reference is readable.
//
// The prompt text assembled below (buildVariantBPrompt and its helpers) is a
// verbatim — not paraphrased — port of core/agent.py's generate_email_content
// task_instructions/prompt f-strings. An earlier revision of this file
// paraphrased that text; see the phase-4 follow-up report for the fix.
func (a *Agent) GenerateEmailContent(ctx context.Context, in GenerateEmailContentInput) (*model.GeneratedContent, error) {
	// --- Upload hero/logo images to the HubSpot CDN, falling back to the raw
	// scraped URL on upload failure (ports `hero_img = _upload_img(hero_img)
	// or hero_img` / `logo_img = _upload_img(logo_img) or logo_img`).
	// banner_url is hero_img only — Python never substitutes logo_img as a
	// banner fallback. ---
	heroURL := in.EventDetails.HeroImageURL
	if heroURL != "" {
		if uploaded, _ := a.Emails.UploadImageToHubSpot(ctx, heroURL, "banner.jpg"); uploaded != "" {
			heroURL = uploaded
		}
	}
	bannerURL := heroURL

	// --- Upload sponsor logos, falling back to the raw logo URL on upload
	// failure (ports `cdn_logo = _upload_img(raw_logo) or raw_logo`); a
	// sponsor is only dropped when it has no logo_url at all. ---
	var uploadedSponsors []model.Sponsor
	for i, sp := range in.EventDetails.Sponsors {
		if sp.LogoURL == "" {
			continue
		}
		logoURL := sp.LogoURL
		if uploaded, err := a.Emails.UploadImageToHubSpot(ctx, sp.LogoURL, fmt.Sprintf("sponsor_%d.jpg", i)); err == nil && uploaded != "" {
			logoURL = uploaded
		}
		tier := "tier1"
		if i >= 3 {
			tier = "tier2"
		}
		uploadedSponsors = append(uploadedSponsors, model.Sponsor{Name: sp.Name, Logo: logoURL, Tier: tier})
	}

	// --- Read up to 3 reference emails, pick the richest as primary. ---
	refIDs := in.ReferenceIDs
	if len(refIDs) == 0 && in.SourceEmailID != "" {
		refIDs = []string{in.SourceEmailID}
	}
	refs := make([]referenceEmail, 0, len(refIDs))
	for i, id := range refIDs {
		if i >= 3 {
			break
		}
		if id == "" {
			continue
		}
		content, err := a.Emails.GetEmailContentText(ctx, id)
		if err != nil || content == nil || !content.Success {
			continue
		}
		if len(content.Sections) == 0 && content.BodyHTML == "" {
			continue
		}
		refs = append(refs, referenceEmail{Content: content, Richness: richness(content)})
	}

	var primary *referenceEmail
	if len(refs) > 0 {
		sort.SliceStable(refs, func(i, j int) bool { return refs[i].Richness > refs[j].Richness })
		primary = &refs[0]
	}

	refBtnColor := "#04c0da"
	var refBlock, styleBlock, templateBlock string
	if primary != nil {
		refBtnColor = firstButtonColor(primary.Content.Sections, refBtnColor)
		refBlock = buildRefBlock(primary.Content)
		styleBlock = buildStyleBlock(refs)
	} else {
		tmpl, ok := emailtemplates.GetTemplate(in.Stage.Name, nil)
		if !ok {
			tmpl, _ = emailtemplates.GetTemplate("Event Announcement", nil)
		}
		if tmpl != nil {
			templateBlock = fmt.Sprintf(
				"━━━ STAGE TEMPLATE (use when no reference email is available) ━━━━━━━━━━━━\nSubject   : %s\nPreheader : %s\n\nBody:\n%s\n",
				tmpl.Subject, tmpl.Preheader, tmpl.Body,
			)
		}
	}

	prompt := buildVariantBPrompt(in, refBlock, templateBlock, styleBlock, refBtnColor, uploadedSponsors, a.now().Format("January 02, 2006"))

	text, err := a.claudeText(ctx, prompt, 6000, 480, 90)
	if err != nil {
		return nil, err
	}

	cleaned := stripMarkdownFences(text)
	block, ok := balancedJSONBlock(cleaned)
	if !ok {
		return nil, fmt.Errorf("generate_email_content: model did not return a JSON object")
	}

	var parsed struct {
		Subject     string               `json:"subject"`
		PreviewText string               `json:"preview_text"`
		HTML        string               `json:"html"`
		Sections    []model.EmailSection `json:"sections"`
	}
	if err := json.Unmarshal([]byte(block), &parsed); err != nil {
		// Ports the break-on-JSONDecodeError branch: no further attempts
		// are made once the balanced block fails to parse.
		return nil, fmt.Errorf("generate_email_content: failed to parse model JSON: %w", err)
	}

	sections := parsed.Sections
	// Backwards compat: if Claude returned "html" instead of "sections".
	if len(sections) == 0 && parsed.HTML != "" {
		sections = []model.EmailSection{{"type": "rich_text", "html": parsed.HTML}}
	}

	sections = dropSystemSections(sections, uploadedSponsors)
	bodyHTML := sectionsToHTML(sections, refBtnColor, uploadedSponsors)
	previewHTML := buildEmailPreview(bannerURL, bodyHTML, in.EventDetails.URL, in.EventDetails.EventName)

	return &model.GeneratedContent{
		Subject:     parsed.Subject,
		PreviewText: parsed.PreviewText,
		HTML:        previewHTML,
		BodyHTML:    bodyHTML,
		Sections:    sections,
		Sponsors:    uploadedSponsors,
		BannerURL:   bannerURL,
	}, nil
}

func firstButtonColor(sections []model.ContentSection, def string) string {
	for _, s := range sections {
		if s.Type == "button" && s.BackgroundColor != "" {
			return s.BackgroundColor
		}
	}
	return def
}

// buildRefBlock ports the ref_block construction verbatim: a
// component-by-component layout description plus the raw rich-text HTML of
// the primary reference email.
func buildRefBlock(ref *model.EmailContentText) string {
	var lines []string
	for i, comp := range ref.Sections {
		idx := i + 1
		switch comp.Type {
		case "image":
			lines = append(lines, fmt.Sprintf("  [%d] IMAGE — hero banner (full-width event graphic)", idx))
		case "image_row":
			alts := make([]string, 0, len(comp.Images))
			for _, im := range comp.Images {
				alt := im.Alt
				if alt == "" {
					alt = "?"
				}
				alts = append(alts, alt)
			}
			lines = append(lines, fmt.Sprintf("  [%d] IMAGE ROW (%d columns) — sponsor logos: %s", idx, len(comp.Images), strings.Join(alts, ", ")))
		case "rich_text":
			preview := stripTagsRe.ReplaceAllString(comp.HTML, "")
			if len(preview) > 80 {
				preview = preview[:80]
			}
			preview = strings.TrimSpace(preview)
			lines = append(lines, fmt.Sprintf("  [%d] RICH TEXT — \"%s…\"", idx, preview))
		case "button":
			bg := comp.BackgroundColor
			if bg == "" {
				bg = "#04c0da"
			}
			lines = append(lines, fmt.Sprintf("  [%d] BUTTON — \"%s\" bg=%s", idx, comp.Text, bg))
		case "divider":
			style := comp.Style
			if style == "" {
				style = "solid"
			}
			height := comp.Height
			if height == 0 {
				height = 1
			}
			lines = append(lines, fmt.Sprintf("  [%d] DIVIDER — %s %dpx", idx, style, height))
		case "social_icons":
			lines = append(lines, fmt.Sprintf("  [%d] SOCIAL ICONS — %s", idx, pythonListRepr(comp.Networks)))
		}
	}

	return fmt.Sprintf(
		"━━━ PRIMARY REFERENCE EMAIL (mirror THIS structure) ━━━━━━━━━━━━━━━━━━━━━\nName    : %s\nSubject : %s\nPreview : %s\n\nCOMPONENT LAYOUT (replicate this exact sequence):\n%s\n\nRICH TEXT HTML (actual HTML from each text block, in order):\n%s\n",
		ref.EmailName, ref.Subject, ref.PreviewText, strings.Join(lines, "\n"), ref.BodyHTML,
	)
}

// buildStyleBlock ports the style/tone corpus built from ALL read references
// (not just the primary), each truncated to 900 chars of tag-stripped body
// text.
func buildStyleBlock(refs []referenceEmail) string {
	var parts []string
	for k, r := range refs {
		txt := stripTagsRe.ReplaceAllString(r.Content.BodyHTML, " ")
		txt = strings.TrimSpace(collapseWhitespaceRe.ReplaceAllString(txt, " "))
		if len(txt) > 900 {
			txt = txt[:900]
		}
		if txt == "" {
			continue
		}
		parts = append(parts, fmt.Sprintf("[Ref %d] %s\n  Subject: %s\n  Body voice sample: %s", k+1, r.Content.EmailName, r.Content.Subject, txt))
	}
	if len(parts) == 0 {
		return ""
	}
	return "━━━ STYLE & TONE REFERENCES (learn the house voice from ALL of these) ━━━\n" +
		"These are real past emails for this brand. Match their tone, voice, greeting\n" +
		"and sign-off style, sentence rhythm, emoji usage, and CTA phrasing. Do NOT\n" +
		"copy their event-specific facts (names, dates, prices) — only the STYLE.\n\n" +
		strings.Join(parts, "\n\n") + "\n"
}

// pythonListRepr renders a []string the way Python's str(list) does, e.g.
// ['a', 'b'] or [] — used only inside the SOCIAL ICONS layout line, which
// echoes the raw list via an f-string {comp.get('networks', [])}.
func pythonListRepr(items []string) string {
	if len(items) == 0 {
		return "[]"
	}
	quoted := make([]string, len(items))
	for i, s := range items {
		quoted[i] = "'" + s + "'"
	}
	return "[" + strings.Join(quoted, ", ") + "]"
}

var linkLabelOrder = []struct {
	key   string
	label string
}{
	{"register", "Registration page"},
	{"sponsor", "Sponsorship page"},
	{"cfp", "Call for Proposals / submit a talk or poster"},
	{"schedule", "Schedule / agenda page"},
	{"venue", "Venue & travel page"},
}

func eventLinksGet(links model.EventLinks, key string) string {
	switch key {
	case "register":
		return links.Register
	case "sponsor":
		return links.Sponsor
	case "cfp":
		return links.CFP
	case "schedule":
		return links.Schedule
	case "venue":
		return links.Venue
	}
	return ""
}

// buildLinksBlock ports the links_block f-string verbatim, including the
// per-purpose CTA routing rule text.
func buildLinksBlock(links model.EventLinks, mainURL string) string {
	var lines []string
	for _, l := range linkLabelOrder {
		if v := eventLinksGet(links, l.key); v != "" {
			lines = append(lines, fmt.Sprintf("  • %s: %s", l.label, v))
		}
	}
	body := "  (only the main event page is available)"
	if len(lines) > 0 {
		body = strings.Join(lines, "\n")
	}
	return "━━━ EVENT LINKS — point each CTA at the CORRECT page ━━━━━━━━━━━━━━━\n" +
		body +
		fmt.Sprintf("\n  • Main event page: %s\n\n", mainURL) +
		"RULE — set each button's url to the link matching its purpose:\n" +
		"  Register / Save the Date / Attend  → Registration page (else main page)\n" +
		"  Become a Sponsor / Sponsorship     → Sponsorship page\n" +
		"  Submit a Proposal / Talk / Poster / CFP → Call for Proposals link\n" +
		"  View Schedule / Agenda             → Schedule page\n" +
		"  Venue / Travel / Hotel             → Venue & travel page\n" +
		"  Fall back to the main event page ONLY when the specific link is missing.\n" +
		"  Do NOT point every button at the same URL when specific links exist."
}

// buildDateRule ports the CRITICAL DATE AWARENESS block verbatim as used by
// generate_email_content (this variant includes the DURATION CONSISTENCY
// bullet; generate_ai_template_content's own copy, ported separately in
// generate_ai_template_content.go, omits it — matching the Python sources,
// which are two independently-written near-duplicate blocks, not a shared
// helper).
func buildDateRule(todayStr, eventDate, datesDisplay string) string {
	ed := eventDate
	if ed == "" {
		ed = datesDisplay
	}
	if ed == "" {
		ed = "the date above"
	}
	return "━━━ CRITICAL — DATE AWARENESS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n" +
		fmt.Sprintf("Today's date is %s. ", todayStr) +
		fmt.Sprintf("The event takes place on %s.\n", ed) +
		"- NEVER include any registration tier, early-bird price, deadline, or date that\n" +
		"  has ALREADY PASSED relative to today — even if it appears in the reference\n" +
		"  email or event details. Drop expired windows entirely; do not copy them.\n" +
		"- Only mention the registration window / pricing that is currently open or\n" +
		"  still upcoming. If early-bird has ended, reference the current (e.g. standard)\n" +
		"  tier instead, or omit pricing rather than advertising an expired deal.\n" +
		"- Do not invent dates. If unsure whether a date is still valid, omit it.\n" +
		"- DURATION CONSISTENCY: if the event date is a range (e.g. \"August 11-12, 2026\"),\n" +
		"  never describe it as \"a full day\" or \"a day of\" anywhere in the copy — say\n" +
		"  \"two days\" / \"August 11-12\" consistently. Derive the duration word choice\n" +
		"  (day / two days / three days) from the actual date range given above, and use\n" +
		"  the same number of days everywhere in the email — never contradict the dates."
}

// buildVariantBPrompt ports generate_email_content's `prompt` f-string
// verbatim.
func buildVariantBPrompt(in GenerateEmailContentInput, refBlock, templateBlock, styleBlock, refBtnColor string, sponsors []model.Sponsor, todayStr string) string {
	eventName := in.EventDetails.EventName
	location := in.EventDetails.Location
	description := in.EventDetails.Description
	if len(description) > 400 {
		description = description[:400]
	}
	url := in.EventDetails.URL
	speakers := in.EventDetails.Speakers
	topics := in.EventDetails.Topics

	stageName := in.Stage.Name
	funnel := in.Stage.Funnel
	ctaLabel := in.Stage.CTALabel
	if ctaLabel == "" {
		ctaLabel = "Register Now"
	}
	eventDate := in.Stage.EventDateStr
	datesDisplay := ""
	if len(in.EventDetails.EventDates) > 0 {
		datesDisplay = in.EventDetails.EventDates[0]
	}
	if eventDate == "" {
		eventDate = datesDisplay
	}
	marketingStrategy := in.Stage.MarketingStrategy
	contentIdeas := in.Stage.ContentIdeas

	speakersStr := "  (to be announced)"
	if len(speakers) > 0 {
		lines := make([]string, len(speakers))
		for i, s := range speakers {
			lines[i] = "  • " + s
		}
		speakersStr = strings.Join(lines, "\n")
	}

	sponsorsStr := "  (not listed on event page)"
	if len(sponsors) > 0 {
		lines := make([]string, 0, len(sponsors))
		for _, s := range sponsors {
			line := "  • " + s.Name
			if s.Logo != "" {
				line += fmt.Sprintf("  [logo: %s]", s.Logo)
			}
			lines = append(lines, line)
		}
		sponsorsStr = strings.Join(lines, "\n")
	}

	topicsStr := "Open Source, Cloud Native, Linux"
	if len(topics) > 0 {
		n := len(topics)
		if n > 4 {
			n = 4
		}
		topicsStr = strings.Join(topics[:n], ", ")
	}

	hsFirstname := "{{ contact.firstname }}"
	hsCompany := "{{ contact.company }}"

	reg := in.EventDetails.Registration
	var regLines []string
	if len(reg.TicketTypes) > 0 {
		n := len(reg.TicketTypes)
		if n > 2 {
			n = 2
		}
		regLines = append(regLines, "Ticket info: "+strings.Join(reg.TicketTypes[:n], "; "))
	}
	if len(reg.Deadlines) > 0 {
		regLines = append(regLines, "Deadline: "+reg.Deadlines[0])
	}
	if reg.URL != "" {
		regLines = append(regLines, "Register at: "+reg.URL)
	}
	regInfo := strings.Join(regLines, "\n")

	linksBlock := buildLinksBlock(in.EventDetails.Links, url)
	dateRule := buildDateRule(todayStr, eventDate, datesDisplay)

	taskInstructions := buildTaskInstructions(refBlock != "", stageName, funnel, ctaLabel, refBtnColor, hsFirstname, hsCompany, marketingStrategy, contentIdeas)

	stageNumLabel := ""
	if in.Stage.StageNumber != nil {
		stageNumLabel = fmt.Sprintf("Stage %d — ", *in.Stage.StageNumber)
	}

	primaryBlock := refBlock
	if primaryBlock == "" {
		primaryBlock = templateBlock
	}

	changeRequestBlock := ""
	if in.ChangeRequest != "" {
		changeRequestBlock = "\n━━━ CHANGE REQUEST ━━━\n" + in.ChangeRequest + "\n"
	}

	var b strings.Builder
	b.WriteString("You are a senior email marketer for Linux Foundation open source events.\n\n")
	b.WriteString(primaryBlock)
	b.WriteString("\n")
	b.WriteString(styleBlock)
	b.WriteString("━━━ NEW EVENT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
	fmt.Fprintf(&b, "Event Name  : %s\n", eventName)
	fmt.Fprintf(&b, "Date        : %s\n", datesDisplay)
	fmt.Fprintf(&b, "Location    : %s\n", location)
	fmt.Fprintf(&b, "Event URL   : %s\n", url)
	fmt.Fprintf(&b, "Description : %s\n", description)
	fmt.Fprintf(&b, "Stage       : %s%s (%s)\n\n", stageNumLabel, stageName, funnel)
	b.WriteString("Confirmed Speakers:\n")
	b.WriteString(speakersStr)
	b.WriteString("\n\n")
	b.WriteString("Sponsors / Partners:\n")
	b.WriteString(sponsorsStr)
	b.WriteString("\n\n")
	fmt.Fprintf(&b, "Topics      : %s\n", topicsStr)
	b.WriteString(regInfo)
	b.WriteString("\n\n")
	b.WriteString(linksBlock)
	b.WriteString("\n\n")
	b.WriteString(dateRule)
	b.WriteString("\n\n")
	b.WriteString(taskInstructions)
	b.WriteString("\n\n")
	b.WriteString("Return ONLY a JSON object — no markdown fences, no text before or after:\n")
	b.WriteString(`{"subject": "...", "preview_text": "...", "sections": [...]}`)
	b.WriteString("\n\n")
	fmt.Fprintf(&b, "subject: email subject line (max 60 chars, matches %s urgency)\n", stageName)
	b.WriteString("preview_text: preheader text (max 90 chars)\n")
	b.WriteString("sections: ordered array of content blocks. The system automatically adds the hero\n")
	b.WriteString("  banner image, sponsor images/names, social icons footer, and unsubscribe footer —\n")
	b.WriteString("  do NOT include those.\n\n")
	b.WriteString("  Each block must be one of:\n")
	b.WriteString(`    Rich text: {"type": "rich_text", "html": "<p style='...'>...</p>"}` + "\n")
	b.WriteString(`    CTA button: {"type": "button", "text": "REGISTER NOW >>", "url": "https://...", "color": "#46b6b3"}` + "\n\n")
	b.WriteString("  CRITICAL:\n")
	b.WriteString("    - Do NOT embed buttons as HTML in rich_text blocks — separate button objects only.\n")
	b.WriteString("    - Do NOT include sponsor images, sponsor names, banner, footer, or social icons.\n")
	b.WriteString("    - rich_text \"html\" must NOT have an outer <div> wrapper — just the inner content.\n")
	b.WriteString(changeRequestBlock)
	return b.String()
}

// buildTaskInstructions ports the two task_instructions branches
// (reference-driven vs fallback-template), verbatim, including the
// MARKETING STRATEGY / CONTENT IDEAS sub-block that only appears inside the
// reference-driven branch (6-idea cap) vs. the differently-formatted,
// 5-idea-cap inline mention in the fallback branch.
func buildTaskInstructions(hasRef bool, stageName, funnel, ctaLabel, refBtnColor, hsFirstname, hsCompany, marketingStrategy string, contentIdeas []string) string {
	if hasRef {
		var strategyBlock string
		if marketingStrategy != "" {
			strategyBlock = "MARKETING STRATEGY FOR THIS STAGE (use as messaging direction):\n  " + marketingStrategy
		}
		var ideasBlock string
		if len(contentIdeas) > 0 {
			n := len(contentIdeas)
			if n > 6 {
				n = 6
			}
			lines := make([]string, n)
			for i, idea := range contentIdeas[:n] {
				lines[i] = "  • " + idea
			}
			ideasBlock = "CONTENT IDEAS FOR THIS STAGE (draw from these for section headlines & copy):\n" + strings.Join(lines, "\n")
		}

		var b strings.Builder
		b.WriteString("━━━ YOUR TASK ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
		b.WriteString("You are given a COMPONENT LAYOUT and RICH TEXT HTML from a real previously sent\n")
		b.WriteString("email. Build a new email for the event below that follows the same design exactly.\n\n")
		b.WriteString("═══ COMPONENT-BY-COMPONENT RULES ═══════════════════════════════════════════════\n\n")
		b.WriteString("For each component in the COMPONENT LAYOUT above, output the matching HTML:\n\n")
		b.WriteString("▸ IMAGE (hero banner)\n")
		b.WriteString("  — The system injects the hero banner automatically. Skip this in your output.\n\n")
		b.WriteString("▸ RICH TEXT blocks\n")
		b.WriteString("  — Copy the inline CSS from the reference HTML exactly (font-size, line-height,\n")
		b.WriteString("    color, background-color, text-align, font-weight).\n")
		b.WriteString("  — Keep the same heading style: if the reference uses <p> with inline bold+size,\n")
		b.WriteString("    use <p>; if it uses <h2>, use <h2>. Do NOT switch tag types.\n")
		b.WriteString("  — Keep emoji prefixes on section headings (💡 🎟️ 🤝 etc.) — pick appropriate\n")
		b.WriteString("    emoji for each section based on the stage context.\n")
		b.WriteString("  — Replace all event-specific text (name, date, location, URL, topics, speakers,\n")
		b.WriteString("    sponsors) with the new event's details.\n")
		b.WriteString("  — Keep body text font-size and color identical to the reference.\n\n")
		b.WriteString("▸ BUTTON\n")
		b.WriteString("  — For every CTA, output a SEPARATE button section object:\n")
		fmt.Fprintf(&b, "    {\"type\": \"button\", \"text\": \"REGISTER NOW >>\", \"url\": \"https://...\", \"color\": \"%s\"}\n", refBtnColor)
		b.WriteString("  — Do NOT embed button HTML inside a rich_text section.\n")
		fmt.Fprintf(&b, "  — Button text must match the stage CTA: \"%s\"\n", ctaLabel)
		b.WriteString("  — If reference has multiple CTAs (one per section), output the same number of button sections.\n\n")
		b.WriteString("▸ DIVIDER\n")
		b.WriteString("  — Between major content sections, end the rich_text html with:\n")
		b.WriteString("    <hr style=\"border:none;border-top:1px solid #000000;margin:20px 0;\">\n\n")
		b.WriteString("▸ IMAGE ROW (sponsor logos)\n")
		b.WriteString("  — The system adds sponsor images automatically as native HubSpot image modules.\n")
		b.WriteString("  — Do NOT include sponsor images or logos in any section.\n")
		b.WriteString("  — Do NOT include sponsor names in the HTML sections either — the system handles them.\n")
		b.WriteString("  — Do NOT include a \"Thank You to Our Sponsors!\" heading or any sponsor section header —\n")
		b.WriteString("    the system injects this heading automatically before the sponsor logos.\n\n")
		b.WriteString("▸ GREETING SPACING\n")
		fmt.Fprintf(&b, "  — If the greeting line uses a name/firstname token (e.g. \"Hi %s,\"),\n", hsFirstname)
		b.WriteString("    put it in its own <p> tag with margin-bottom (e.g. margin:0 0 12px;) — never\n")
		b.WriteString("    run the greeting and the next sentence together in the same <p> or joined by <br>.\n\n")
		b.WriteString("▸ NO SIGN-OFF\n")
		b.WriteString("  — Do NOT include a closing sign-off line such as \"Regards,\", \"Best,\", \"Sincerely,\",\n")
		b.WriteString("    \"The Linux Foundation\", or any similar valediction anywhere in the body. If the\n")
		b.WriteString("    reference email's rich-text HTML contains one (often a leftover artifact from an\n")
		b.WriteString("    earlier cloned/reused email), drop it — do not copy it into the new email.\n\n")
		b.WriteString("▸ STRICT SECTION ORDER — output section objects in this exact sequence:\n")
		b.WriteString("  1. Greeting / intro paragraph  (rich_text)\n")
		b.WriteString("  2. Event highlights / main body  (rich_text)\n")
		b.WriteString("  3. Speakers section if speakers available  (rich_text)\n")
		b.WriteString("  4. Topics / tracks if available  (rich_text)\n")
		b.WriteString("  5. CTA button  (button section)\n")
		b.WriteString("  6. Additional CTAs if reference had multiple  (button sections)\n")
		b.WriteString("  Sponsors are added by the system after your last section — do NOT output them.\n\n")
		b.WriteString("▸ SOCIAL ICONS / FOOTER / BANNER\n")
		b.WriteString("  — The system injects banner, footer, social icons automatically. Skip in your output.\n")
		b.WriteString("  — Do NOT include: \"This email was sent by\", address, \"Subscription Center\", \"Unsubscribe\",\n")
		b.WriteString("    \"{{ unsubscribe_link }}\", or any footer-related text — the system adds these.\n\n")
		b.WriteString("═══ STAGE & CONTENT RULES ═══════════════════════════════════════════════════════\n")
		fmt.Fprintf(&b, "Stage: %s (%s)\n", stageName, funnel)
		fmt.Fprintf(&b, "Primary CTA: \"%s\"\n", ctaLabel)
		b.WriteString("- Tailor headlines, urgency wording, and section focus to match this stage.\n")
		b.WriteString("- CFP stage → focus on speaking topics, deadline, submission link.\n")
		b.WriteString("- Registration stage → focus on early bird pricing, date, venue.\n")
		b.WriteString("- Announcement stage → focus on event overview, why attend, save the date.\n\n")
		b.WriteString(strategyBlock)
		b.WriteString("\n\n")
		b.WriteString(ideasBlock)
		b.WriteString("\n\n")
		b.WriteString("DESIGN RULE: Copy the EXACT design, layout, and component structure from the reference email\n")
		b.WriteString("above. Only the copy/messaging/content changes — never the visual structure or styling.\n\n")
		b.WriteString("Speaker list: include ALL confirmed speakers (never say \"and more\").\n")
		b.WriteString("Sponsor list: include ALL sponsors (never say \"and more\" — but do NOT render them in sections).\n\n")
		b.WriteString("HubSpot personalization tokens (exact syntax — spaces and dots matter):\n")
		fmt.Fprintf(&b, "  First name : %s\n", hsFirstname)
		fmt.Fprintf(&b, "  Company    : %s\n\n", hsCompany)
		b.WriteString("═══ OUTPUT FORMAT ════════════════════════════════════════════════════════════════\n")
		b.WriteString("- Output sections in the JSON sections array — NOT as a single HTML block.\n")
		b.WriteString("- Each rich_text \"html\" value: inline HTML paragraphs/lists only. No outer <div> wrapper.\n")
		b.WriteString("  Use inline CSS (font-size, line-height, color, text-align, etc.) — no <style> tags.\n")
		b.WriteString("- Each CTA button: a separate button section object — NOT embedded HTML in rich_text.\n")
		b.WriteString("- Do NOT include: <html>, <head>, <body>, outer <div> wrapper, banner image,\n")
		b.WriteString("  sponsor images/names, social icons, footer, or unsubscribe content.\n")
		b.WriteString("- Bullet lists: <ul>/<li> tags — never the • character.")
		return b.String()
	}

	var b strings.Builder
	b.WriteString("━━━ YOUR TASK ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
	b.WriteString("Replace every placeholder ([Event Name], [City], [Dates], [LINK], etc.) with\n")
	b.WriteString("the real event details above and produce an ordered sections array.\n\n")
	fmt.Fprintf(&b, "1. Stage: %s (%s) — CTA: \"%s\"\n", stageName, funnel, ctaLabel)
	if marketingStrategy != "" {
		fmt.Fprintf(&b, "   Marketing strategy: %s\n", marketingStrategy)
	}
	if len(contentIdeas) > 0 {
		n := len(contentIdeas)
		if n > 5 {
			n = 5
		}
		b.WriteString("   Content ideas (draw from these for section copy):\n")
		for _, idea := range contentIdeas[:n] {
			fmt.Fprintf(&b, "   • %s\n", idea)
		}
	}
	b.WriteString("\n2. Include ALL speakers listed (with names — do not say \"and more\").\n")
	b.WriteString("3. Do NOT include sponsor images/names — the system adds them as native modules.\n\n")
	b.WriteString("4. HubSpot personalization tokens (EXACT syntax):\n")
	fmt.Fprintf(&b, "   - First name : %s\n", hsFirstname)
	fmt.Fprintf(&b, "   - Company    : %s\n", hsCompany)
	fmt.Fprintf(&b, "   - Greeting spacing: if the greeting uses a name/firstname token (e.g. \"Hi %s,\"),\n", hsFirstname)
	b.WriteString("     put it in its own <p> tag with margin-bottom (e.g. margin:0 0 12px;) — never run the\n")
	b.WriteString("     greeting and the next sentence together in the same <p> or joined by <br>.\n\n")
	b.WriteString("4b. NO SIGN-OFF: do NOT include a closing sign-off line such as \"Regards,\", \"Best,\",\n")
	b.WriteString("    \"Sincerely,\" or \"The Linux Foundation\" anywhere in the body — drop any such line\n")
	b.WriteString("    even if it appears in reference/cloned content.\n\n")
	b.WriteString("5. Output sections array — NOT a single HTML block:\n")
	b.WriteString("   - rich_text sections: inline HTML only (no outer div wrapper, no style tags)\n")
	b.WriteString("   - button sections: {\"type\":\"button\",\"text\":\"...\",\"url\":\"...\",\"color\":\"#04c0da\"}\n")
	b.WriteString("   - Do NOT include banner, sponsor images, footer, or unsubscribe content.\n")
	b.WriteString("   Bullet lists as <ul>/<li>. Inline CSS only.")
	return b.String()
}
