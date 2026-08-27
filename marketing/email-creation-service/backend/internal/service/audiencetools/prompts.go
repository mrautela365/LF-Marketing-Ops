package audiencetools

import "strings"

// Prescraped mirrors the subset of session.Meta["url_data"] that
// _format_prescraped_step1 reads — already-scraped event data from the
// Email Content wizard stage, reused here to skip a second web_fetch.
type Prescraped struct {
	EventDates  []string
	Headings    []string
	EventName   string
	BrandName   string
	Location    string
	Description string
}

func firstOr(s, fallback string) string {
	if s == "" {
		return fallback
	}
	return s
}

func joinOr(vals []string, fallback string) string {
	if len(vals) == 0 {
		return fallback
	}
	return strings.Join(vals, ", ")
}

// formatPrescrapedStep1 ports _format_prescraped_step1 verbatim.
func formatPrescrapedStep1(data Prescraped) string {
	dates := joinOr(data.EventDates, "unknown")
	headings := joinOr(data.Headings, "none captured")
	var b strings.Builder
	b.WriteString("═══════════════════════════════════════════════════\n")
	b.WriteString("STEP 1 — Event details (already scraped — do NOT re-fetch the page)\n")
	b.WriteString("═══════════════════════════════════════════════════\n")
	b.WriteString("The event page was already scraped while drafting the email content. Use this data\n")
	b.WriteString("directly instead of calling web_fetch on the URL above:\n\n")
	b.WriteString("- Event name: " + firstOr(data.EventName, "unknown") + "\n")
	b.WriteString("- Foundation / brand: " + firstOr(data.BrandName, "unknown") + "\n")
	b.WriteString("- Location: " + firstOr(data.Location, "unknown") + "\n")
	b.WriteString("- Event dates: " + dates + "\n")
	b.WriteString("- Description: " + firstOr(data.Description, "unknown") + "\n")
	b.WriteString("- Page headings: " + headings + "\n\n")
	b.WriteString("Derive the short name / slug, event type, and the Product/technology domain\n")
	b.WriteString("(HARDWARE vs SOFTWARE/AI bucket + specific project/technology focus — see the\n")
	b.WriteString("CRITICAL \"Product/technology domain fit\" note above) from the description and\n")
	b.WriteString("page headings above. Do NOT call web_fetch for this URL — it has already been\n")
	b.WriteString("scraped and re-fetching would waste a step. Only fall back to web_fetch if a\n")
	b.WriteString("detail you need is genuinely missing from the data above.\n")
	return b.String()
}

// BuildPlanningPrompt ports build_planning_prompt verbatim.
func BuildPlanningPrompt(url string, prescraped *Prescraped, qa string) string {
	step1 := step1Scrape
	if prescraped != nil {
		step1 = formatPrescrapedStep1(*prescraped)
	}
	prompt := strings.ReplaceAll(planningPromptTemplate, "__URL__", url)
	prompt = strings.ReplaceAll(prompt, "__STEP1__", step1)
	if qa != "" {
		prompt += "\n\nThe user has already answered these clarifying questions from a prior " +
			"planning pass — incorporate the answers directly, do not ask them again:\n" + qa + "\n"
	}
	return prompt
}

// qaSection ports the `f"\nUser answers to clarifying questions:\n{qa}\n" if qa else ""`
// idiom repeated across start_build_job/_run_two_phase/start_custom_build_job/
// _run_custom_two_phase.
func qaSection(qa string) string {
	if qa == "" {
		return ""
	}
	return "\nUser answers to clarifying questions:\n" + qa + "\n"
}

// BuildBuildingPrompt ports the inline BUILDING_PROMPT.format(url=, plan=,
// qa_section=) calls in start_build_job / _run_two_phase.
func BuildBuildingPrompt(url, plan, qa string) string {
	prompt := strings.ReplaceAll(buildingPromptTemplate, "__URL__", url)
	prompt = strings.ReplaceAll(prompt, "__PLAN__", plan)
	prompt = strings.ReplaceAll(prompt, "__QA_SECTION__", qaSection(qa))
	return prompt
}

// BuildCustomPlanningPrompt ports build_custom_planning_prompt verbatim.
func BuildCustomPlanningPrompt(requestText, qa string) string {
	prompt := strings.ReplaceAll(customPlanningPromptTemplate, "__REQUEST__", requestText)
	if qa != "" {
		prompt += "\n\nThe user has already answered these clarifying questions from a prior " +
			"planning pass — incorporate the answers directly, do not ask them again:\n" + qa + "\n"
	}
	return prompt
}

// BuildCustomBuildingPrompt ports the inline CUSTOM_BUILDING_PROMPT.format(...)
// calls in start_custom_build_job / _run_custom_two_phase.
func BuildCustomBuildingPrompt(requestText, plan, qa string) string {
	prompt := strings.ReplaceAll(customBuildingPromptTemplate, "__REQUEST__", requestText)
	prompt = strings.ReplaceAll(prompt, "__PLAN__", plan)
	prompt = strings.ReplaceAll(prompt, "__QA_SECTION__", qaSection(qa))
	return prompt
}
