package wizardagent

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/aiemailtemplates"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/stagedetector"
)

// GenerateAITemplateContent ports generate_ai_template_content — the
// Variant A ("AI Template") generator used ONLY by clone_turn. Unlike
// GenerateEmailContent (Variant B), it is driven exclusively by this event's
// own scraped facts plus the 13-stage marketing-journey data for the
// detected funnel stage (stagedetector.Result's Goal/CTALabel/EventDateStr/
// MarketingStrategy/ContentIdeas/IndustryBestPractices) — never by a
// past-campaign reference email, and (this is the important correction from
// the phase-4 follow-up pass) NOT by aiemailtemplates.GetAITemplate/
// StageTemplate at all. An earlier revision of this file incorrectly gated
// generation on aiemailtemplates.GetAITemplate(stageKey) succeeding and drew
// prompt fields (Purpose/Timing/Tone/ContentPrompt/CTAStrategy/FooterNote)
// from that package's StageTemplate — Python's generate_ai_template_content
// never calls ai_email_templates.get_ai_template() or map_funnel_stage_to_ai_
// template() at all; template_key in its return dict is simply `stage_name`
// (see agent.py line ~2094: `template_key = stage_name`). The mapping helper
// is only used elsewhere (content_turn, ai_template_key computation), not
// here. This file now matches that: TemplateKey is stage.Name, and the
// prompt is built entirely from stagedetector.Result + the event's own
// scraped facts, with aiemailtemplates.AIVariantStyleRules spliced in
// verbatim as a shared style-rules block (that constant is an
// already-ported sibling module, reused as-is, not re-authored here).
//
// bannerURL/sponsors are expected to already be uploaded (reused from the
// Variant B call earlier in the same clone_turn run) rather than uploaded
// again here.
func (a *Agent) GenerateAITemplateContent(ctx context.Context, eventDetails model.ScrapedEventFull, stage stagedetector.Result, bannerURL string, sponsors []model.Sponsor) *model.AITemplateContent {
	// sponsors/bannerURL/template_key/stage_name are computed before any
	// generation step so they remain available even if generation fails
	// below — mirrors Python computing them ahead of the try block.
	result := &model.AITemplateContent{
		Sponsors:    sponsors,
		BannerURL:   bannerURL,
		StageName:   stage.Name,
		TemplateKey: stage.Name,
	}

	prompt := buildVariantAPrompt(eventDetails, stage, sponsors, a.now().Format("January 02, 2006"))

	text, err := a.claudeText(ctx, prompt, 4000, 480, 90)
	if err != nil {
		result.Mode = "failed"
		result.Error = err.Error()
		return result
	}

	cleaned := stripMarkdownFences(text)

	// Ports the balanced-brace JSON extraction with `continue` (not `break`)
	// on JSONDecodeError — i.e. this generator keeps scanning for a LATER
	// balanced block if the first one fails to parse, unlike
	// GenerateEmailContent's break-on-first-failure behavior. Since our
	// balancedJSONBlock only returns the first block, we emulate the
	// continue-scanning behavior by retrying from just after each failed
	// block's start brace.
	var parsed struct {
		Subject     string               `json:"subject"`
		PreviewText string               `json:"preview_text"`
		HTML        string               `json:"html"`
		Sections    []model.EmailSection `json:"sections"`
	}
	remaining := cleaned
	parsedOK := false
	for {
		block, ok := balancedJSONBlock(remaining)
		if !ok {
			break
		}
		if err := json.Unmarshal([]byte(block), &parsed); err == nil {
			parsedOK = true
			break
		}
		idx := strings.Index(remaining, block)
		if idx < 0 {
			break
		}
		remaining = remaining[idx+1:]
	}

	if !parsedOK {
		result.Mode = "failed"
		result.Error = "generate_ai_template_content: model did not return a parseable JSON object"
		return result
	}

	sections := parsed.Sections
	if len(sections) == 0 && parsed.HTML != "" {
		sections = []model.EmailSection{{"type": "rich_text", "html": parsed.HTML}}
	}
	sections = dropSystemSections(sections, sponsors)

	// Safety net for AI_VARIANT_STYLE_RULES' "no em dash" instruction — strip
	// any em/en dash the model used anyway, in subject/preview/every
	// section's copy. Variant A applies this; Variant B never does.
	for i := range sections {
		if html, ok := sections[i]["html"].(string); ok {
			sections[i]["html"] = aiemailtemplates.StripEmDashes(html)
		}
		if text, ok := sections[i]["text"].(string); ok {
			sections[i]["text"] = aiemailtemplates.StripEmDashes(text)
		}
	}

	bodyHTML := sectionsToHTML(sections, "#04c0da", sponsors)
	previewHTML := buildEmailPreview(bannerURL, bodyHTML, eventDetails.URL, eventDetails.EventName)

	result.Subject = aiemailtemplates.StripEmDashes(parsed.Subject)
	result.PreviewText = aiemailtemplates.StripEmDashes(parsed.PreviewText)
	result.BodyHTML = bodyHTML
	result.Sections = sections
	result.HTML = previewHTML
	result.Mode = "ai-generated"
	return result
}

// buildExtraDetailBlock ports the WHO SHOULD ATTEND / WHAT'S INCLUDED block
// verbatim, each capped at 6 real scraped facts.
func buildExtraDetailBlock(audience, inclusions []string) string {
	var b strings.Builder
	if len(audience) > 0 {
		n := len(audience)
		if n > 6 {
			n = 6
		}
		b.WriteString("\nWHO SHOULD ATTEND (real facts scraped from the event page — include EVERY\n")
		b.WriteString("one of these as its own 'Who Should Attend' bullet; do not merge, condense,\n")
		b.WriteString("paraphrase-and-drop, or invent additional ones):\n")
		for _, a := range audience[:n] {
			fmt.Fprintf(&b, "  • %s\n", a)
		}
	}
	if len(inclusions) > 0 {
		n := len(inclusions)
		if n > 6 {
			n = 6
		}
		b.WriteString("\nWHAT'S INCLUDED (real facts scraped from the event/registration page — turn\n")
		b.WriteString("these into a short 'What's Included' bullet list, do not invent additional ones):\n")
		for _, i := range inclusions[:n] {
			fmt.Fprintf(&b, "  • %s\n", i)
		}
	}
	return b.String()
}

// buildLinksBlockShort ports generate_ai_template_content's own (shorter)
// links_block f-string — a distinct, independently-written near-duplicate of
// buildLinksBlock in generate_email_content.go, not a shared helper, exactly
// as the two Python functions each define their own links_block text.
func buildLinksBlockShort(links model.EventLinks, mainURL string) string {
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
	return "━━━ EVENT LINKS — point each CTA at the CORRECT page ━━━━━━━━━━━━━━━━━━━━━\n" +
		body +
		fmt.Sprintf("\n  • Main event page: %s\n\n", mainURL) +
		"RULE — set each button's url to the link matching its purpose; fall back to the\n" +
		"main event page ONLY when the specific link is missing."
}

// buildDateRuleVariantA ports generate_ai_template_content's own (distinct)
// CRITICAL DATE AWARENESS block — shorter than generate_email_content's, and
// worded differently around duration consistency; not a shared helper,
// matching the two independent Python f-strings.
func buildDateRuleVariantA(todayStr, eventDate, datesDisplay string) string {
	ed := eventDate
	if ed == "" {
		ed = datesDisplay
	}
	if ed == "" {
		ed = "the date above"
	}
	return "━━━ CRITICAL — DATE AWARENESS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n" +
		fmt.Sprintf("Today's date is %s. The event takes place on ", todayStr) +
		fmt.Sprintf("%s.\n", ed) +
		"- NEVER include a registration tier, early-bird price, or deadline that has\n" +
		"  already passed relative to today. Do not invent dates — omit rather than guess.\n" +
		"- The Date field above is the REAL, complete event date — if it shows a range\n" +
		"  (e.g. \"September 10-11, 2026\"), the event spans that many days. Never\n" +
		"  describe a multi-day event as \"a day\" / \"a full day\" — say \"two days\" or\n" +
		"  cite the exact date range as given, verbatim."
}

// buildVariantAPrompt ports generate_ai_template_content's `prompt`
// f-string verbatim.
func buildVariantAPrompt(eventDetails model.ScrapedEventFull, stage stagedetector.Result, sponsors []model.Sponsor, todayStr string) string {
	eventName := eventDetails.EventName
	if eventName == "" {
		eventName = "Event"
	}
	location := eventDetails.Location
	description := eventDetails.Description
	if len(description) > 400 {
		description = description[:400]
	}
	url := eventDetails.URL
	speakers := eventDetails.Speakers
	topics := eventDetails.Topics
	reg := eventDetails.Registration

	ctaLabel := stage.CTALabel
	if ctaLabel == "" {
		ctaLabel = "Register Now"
	}
	eventDate := stage.EventDateStr
	if eventDate == "" && len(eventDetails.EventDates) > 0 {
		eventDate = eventDetails.EventDates[0]
	}
	datesDisplay := eventDate
	funnel := stage.Funnel
	marketingStrategy := stage.MarketingStrategy
	contentIdeas := stage.ContentIdeas
	bestPractices := stage.IndustryBestPractices
	stageGoal := stage.Goal
	stageName := stage.Name

	speakersStr := "  (to be announced)"
	if len(speakers) > 0 {
		lines := make([]string, len(speakers))
		for i, s := range speakers {
			lines[i] = "  • " + s
		}
		speakersStr = strings.Join(lines, "\n")
	}
	topicsStr := "Open Source, Cloud Native, Linux"
	if len(topics) > 0 {
		n := len(topics)
		if n > 4 {
			n = 4
		}
		topicsStr = strings.Join(topics[:n], ", ")
	}
	sponsorsStr := "  (not listed on event page)"
	if len(sponsors) > 0 {
		lines := make([]string, len(sponsors))
		for i, s := range sponsors {
			lines[i] = "  • " + s.Name
		}
		sponsorsStr = strings.Join(lines, "\n")
	}

	var regLines []string
	if len(reg.TicketTypes) > 0 {
		// Passes ALL scraped tiers (capped at 3 by the scraper already), not
		// just the first 2 like Variant B — see Python's comment on why
		// dropping the current active tier there was a real bug.
		regLines = append(regLines, "Ticket info: "+strings.Join(reg.TicketTypes, "; "))
	}
	if len(reg.Deadlines) > 0 {
		regLines = append(regLines, "Deadline: "+reg.Deadlines[0])
	}
	if reg.URL != "" {
		regLines = append(regLines, "Register at: "+reg.URL)
	}
	regInfo := strings.Join(regLines, "\n")

	extraDetailBlock := buildExtraDetailBlock(eventDetails.Audience, eventDetails.Inclusions)
	linksBlock := buildLinksBlockShort(eventDetails.Links, url)
	dateRule := buildDateRuleVariantA(todayStr, eventDate, datesDisplay)

	hsFirstname := "{{ contact.firstname }}"
	hsCompany := "{{ contact.company }}"

	var marketingStrategyLine string
	if marketingStrategy != "" {
		marketingStrategyLine = "MARKETING STRATEGY FOR THIS STAGE (use as messaging direction):\n  " + marketingStrategy
	}
	var contentIdeasLine string
	if len(contentIdeas) > 0 {
		n := len(contentIdeas)
		if n > 6 {
			n = 6
		}
		lines := make([]string, n)
		for i, idea := range contentIdeas[:n] {
			lines[i] = "  • " + idea
		}
		contentIdeasLine = "CONTENT IDEAS FOR THIS STAGE (draw from these for section headlines & copy):\n" + strings.Join(lines, "\n")
	}
	var bestPracticesBlock string
	if len(bestPractices) > 0 {
		bestPracticesBlock = "━━━ INDUSTRY BEST PRACTICES FOR THIS STAGE (researched, apply these techniques) ━━━━━━\n" +
			fmt.Sprintf("Structure           : %s\n", bestPractices["structure"]) +
			fmt.Sprintf("Clear/actionable CTA: %s\n", bestPractices["cta_guidance"]) +
			fmt.Sprintf("Urgency & FOMO      : %s\n", bestPractices["urgency_fomo_tactics"]) +
			fmt.Sprintf("Specificity         : %s\n", bestPractices["specificity_notes"])
	}

	var b strings.Builder
	b.WriteString("You are a senior email marketer for Linux Foundation open source events,\n")
	b.WriteString("writing Variant A of an A/B test: an \"AI Template\" email generated fresh for this event and\n")
	b.WriteString("this funnel stage, using only this event's own real facts and this stage's own strategy\n")
	b.WriteString("guidance below.\n\n")
	fmt.Fprintf(&b, "━━━ STAGE OBJECTIVE (%s) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n", stageName)
	fmt.Fprintf(&b, "Funnel stage   : %s\n", funnel)
	fmt.Fprintf(&b, "Goal           : %s\n", stageGoal)
	fmt.Fprintf(&b, "Primary CTA    : %s\n\n", ctaLabel)
	b.WriteString(aiemailtemplates.AIVariantStyleRules)
	b.WriteString("\n")
	b.WriteString("━━━ NEW EVENT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
	fmt.Fprintf(&b, "Event Name  : %s\n", eventName)
	fmt.Fprintf(&b, "Date        : %s\n", datesDisplay)
	fmt.Fprintf(&b, "Location    : %s\n", location)
	fmt.Fprintf(&b, "Event URL   : %s\n", url)
	fmt.Fprintf(&b, "Description : %s\n", description)
	fmt.Fprintf(&b, "Stage       : %s (%s)\n\n", stageName, funnel)
	b.WriteString("Confirmed Speakers:\n")
	b.WriteString(speakersStr)
	b.WriteString("\n\n")
	b.WriteString("Sponsors / Partners:\n")
	b.WriteString(sponsorsStr)
	b.WriteString("\n\n")
	fmt.Fprintf(&b, "Topics      : %s\n", topicsStr)
	b.WriteString(regInfo)
	b.WriteString("\n")
	b.WriteString(extraDetailBlock)
	b.WriteString(linksBlock)
	b.WriteString("\n\n")
	b.WriteString(dateRule)
	b.WriteString("\n\n")
	b.WriteString(marketingStrategyLine)
	b.WriteString("\n\n")
	b.WriteString(contentIdeasLine)
	b.WriteString("\n\n")
	b.WriteString(bestPracticesBlock)
	b.WriteString("\n")
	b.WriteString("━━━ YOUR TASK ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
	b.WriteString("Redesign this email from the ground up as a high-converting, urgency-driven\n")
	b.WriteString("lifecycle-marketing email, not as an informational writeup of the event. Your\n")
	b.WriteString("only objective is to maximize clicks on the STAGE OBJECTIVE's primary CTA,\n")
	b.WriteString("using the MARKETING STRATEGY, CONTENT IDEAS, and INDUSTRY BEST PRACTICES for\n")
	b.WriteString("this stage below as your psychology/technique guide. Use ONLY the NEW EVENT's\n")
	b.WriteString("real facts (name, dates, speakers, sponsors, links) — never invent facts from\n")
	b.WriteString("any other source. Prefer fewer, shorter, higher-impact sections over covering\n")
	b.WriteString("every scraped fact.\n\n")
	b.WriteString("RULES:\n")
	b.WriteString("- Never output a literal bracket placeholder like [EVENT_NAME] or [DATE], always\n")
	b.WriteString("  substitute the real value above. If a fact isn't available, write around it instead\n")
	b.WriteString("  of leaving a placeholder in the output.\n")
	b.WriteString("- SECTION ORDER (mandatory, do not reorder):\n")
	b.WriteString("    1. Greeting (short, on its own line/block).\n")
	b.WriteString("    2. ONE short hook block: 1-2 sentences max. Do NOT open by explaining what\n")
	b.WriteString("       the event is. Open with why acting TODAY matters and what's gained or\n")
	b.WriteString("       lost by waiting, using a real fact (price increase, deadline, funding\n")
	b.WriteString("       already under review, limited planning time). No bullets, no event\n")
	b.WriteString("       background here.\n")
	b.WriteString("    3. PRIMARY CTA button — must come immediately after the hook, BEFORE any\n")
	b.WriteString("       bullet lists or detail sections. Never bury the primary CTA below a\n")
	b.WriteString("       wall of details. CTA text fuses action with urgency (see style rules).\n")
	b.WriteString("    4. Supporting sections, most persuasive/relevant first, purely logistical\n")
	b.WriteString("       last — keep only what earns its place:\n")
	b.WriteString("       a. Audience fit, framed persuasively (real scraped \"who should attend\"\n")
	b.WriteString("          facts if given above must all be represented, but woven into a short,\n")
	b.WriteString("          benefit-framed bullet or sentence, not a dry documentation list;\n")
	b.WriteString("          otherwise write brief generic bullets inferred from the description/\n")
	b.WriteString("          topics/speakers — never invent numbers/prices/dates) — lets the\n")
	b.WriteString("          reader immediately self-identify as the target audience.\n")
	b.WriteString("       b. Speakers and topics, framed as outcomes (\"meet/learn from X\"), the\n")
	b.WriteString("          concrete credibility/value payoff.\n")
	b.WriteString("       c. Logistics/inclusions last, and only if a specific inclusion removes a\n")
	b.WriteString("          real objection to acting now — cut generic, non-differentiating\n")
	b.WriteString("          inclusions (coffee, recordings, a t-shirt) rather than listing them\n")
	b.WriteString("          for completeness.\n")
	b.WriteString("    5. A final urgency/FOMO line + secondary CTA button near the end.\n")
	b.WriteString("  Put details, topics, speakers, and dates/deadlines into bullets, not paragraphs.\n")
	b.WriteString("  If a section doesn't build urgency, desire, credibility, or drive the CTA, cut\n")
	b.WriteString("  it or fold it into one shorter sentence elsewhere.\n")
	b.WriteString("- Real styled CTA buttons as separate button sections, built around the Primary CTA\n")
	b.WriteString("  named in STAGE OBJECTIVE above (primary right after the hook per SECTION ORDER, plus\n")
	b.WriteString("  at least one secondary CTA). CTA button text must be a direct action verb\n")
	b.WriteString("  (\"Register Now\", \"Secure Your Seat\", \"Reserve Your Spot Today\", \"View the Agenda\n")
	fmt.Fprintf(&b, "  & Register\") — never a passive/generic label like \"Explore %s\",\n", eventName)
	b.WriteString("  \"Learn More\", or \"Click Here\".\n")
	b.WriteString("- Include ALL confirmed speakers by name (never \"and more\"). Heading the section\n")
	b.WriteString("  \"Featured Speakers\" rather than \"Confirmed Speakers\" unless the data explicitly\n")
	b.WriteString("  says the roster is final.\n")
	b.WriteString("- Do NOT include sponsor images, sponsor names, or a sponsor heading in your sections —\n")
	b.WriteString("  the system adds them automatically as native modules from the sponsors list.\n")
	fmt.Fprintf(&b, "- HubSpot personalization tokens (exact syntax): first name %s, company\n", hsFirstname)
	fmt.Fprintf(&b, "  %s. If the greeting uses a name token, keep it in its own <p> with\n", hsCompany)
	b.WriteString("  margin-bottom — never run it into the next sentence.\n")
	b.WriteString("- No closing sign-off line (\"Regards,\" / \"Best,\" / \"The Linux Foundation\" etc.).\n")
	b.WriteString("- Bullet lists: <ul>/<li> tags — never the • character.\n")
	b.WriteString("- FOMO/urgency is MANDATORY in every email, regardless of funnel stage — never skip\n")
	b.WriteString("  it just because this stage has no hard registration deadline. It must appear at\n")
	b.WriteString("  least twice, in two DIFFERENT spots: once in the step-2 hook (why this matters\n")
	b.WriteString("  now) and once in step 5 near the final CTA. Every stage has SOME real angle:\n")
	b.WriteString("    - If a real deadline/price-increase/CFP-close date exists above, use it directly\n")
	b.WriteString("      (real days-remaining count from today's date, real ticket-tier cutoff, real\n")
	b.WriteString("      submission deadline).\n")
	b.WriteString("    - If no such deadline exists yet (e.g. an early-announcement, post-event, or\n")
	b.WriteString("      ongoing-nurture email), use this stage's Urgency & FOMO guidance from INDUSTRY\n")
	b.WriteString("      BEST PRACTICES above instead — momentum/social proof, limited speaking slots,\n")
	b.WriteString("      \"the only event of its kind\", a what-you-missed angle for past content, or\n")
	b.WriteString("      aspirational \"don't miss next time\" framing. Never invent a fake countdown or\n")
	b.WriteString("      scarcity number just to fill this gap.\n")
	b.WriteString("  Do not repeat the same urgency line twice — vary the wording and the fact/angle used.\n")
	b.WriteString("- NEVER claim venue/seat capacity is limited, \"filling fast\", or \"almost sold out\"\n")
	b.WriteString("  unless that exact claim appears in the scraped facts above — this is a fabricated-\n")
	b.WriteString("  scarcity claim, not a real one. When Ticket info above shows a current price tier\n")
	b.WriteString("  (e.g. a \"Late\"/\"Standard\" tier now in effect vs. a cheaper tier that already\n")
	b.WriteString("  expired), prefer that real price-increase-in-effect fact as your urgency device\n")
	b.WriteString("  over any capacity/scarcity wording.\n\n")
	b.WriteString("═══ OUTPUT FORMAT ════════════════════════════════════════════════════════════════\n")
	b.WriteString("Return ONLY a JSON object — no markdown fences, no text before or after:\n")
	b.WriteString(`{"subject": "...", "preview_text": "...", "sections": [...]}` + "\n\n")
	fmt.Fprintf(&b, "subject: max 60 chars, matches %s's urgency and goal\n", stageName)
	b.WriteString("preview_text: preheader text, max 90 chars\n")
	b.WriteString("sections: ordered array — the system automatically adds the hero banner image, sponsor\n")
	b.WriteString("  images/names, social icons footer, and unsubscribe footer — do NOT include those.\n")
	b.WriteString("  Each block must be one of:\n")
	b.WriteString(`    Rich text: {"type": "rich_text", "html": "<p style='...'>...</p>"}` + "\n")
	b.WriteString(`    CTA button: {"type": "button", "text": "...", "url": "https://...", "color": "#04c0da"}` + "\n")
	b.WriteString("  Do NOT embed buttons as HTML inside rich_text blocks — separate button objects only.\n")
	b.WriteString("  rich_text \"html\" must NOT have an outer <div> wrapper — just the inner content.")
	return b.String()
}
