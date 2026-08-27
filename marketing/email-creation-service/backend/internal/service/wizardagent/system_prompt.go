// Package wizardagent ports backend/core/agent.py from the legacy Python
// service (marketing/emailcreationskill/backend) — the email-staging agent's
// plan/clone/content/chat turns, its tool-execution loop and safety gates,
// and the two content generators used across those turns (Variant A "AI
// Template" and Variant B "reference-driven"). This is a 1:1 behavioral
// port: quirks, redundant logic, and Python-side inconsistencies are kept
// deliberately rather than "fixed" (see the doc comments on the more
// surprising bits, e.g. clone_turn.go's Variant A/B naming swap and
// content_turn.go's dependence on two Python sibling modules that have not
// been ported to Go).
//
// All LLM calls go through domain.LLMGateway (the Go equivalent of Python's
// llm_gateway module) — never a concrete backend directly — so behavior
// stays identical regardless of which LLMGateway implementation the caller
// wires up.
//
// Sibling Python modules this package calls into conceptually (but does NOT
// itself re-port, per the phase-4 scope) are reached through the domain
// ports and already-ported Go service packages:
//   - hubspot_tools / integrations/hubspot.py  -> domain.HubSpotEmailClient,
//     domain.HubSpotListClient (internal/dispatch/hubspot*.go)
//   - content_tools / utils/content_tools.py   -> domain.EventPageScraper
//     (internal/dispatch/webscraper.go)
//   - email_templates / templates/email_templates.py -> internal/service/emailtemplates
//   - ai_email_templates / templates/ai_email_templates.py -> internal/service/aiemailtemplates
//   - event_brands.lookup_event_brand           -> internal/service/eventbrands
//   - stage_detector.detect_stage                -> internal/service/stagedetector
//   - llm_gateway                                 -> domain.LLMGateway / domain.CLISkillRunner
//
// Two Python modules that content_turn.py depends on — generate_ai_content.py
// (generate_variation_b_email) and analyze_email_content.py
// (analyze_and_improve_email) — have NOT been ported to Go by any prior phase
// and are out of this phase's scope too. See content_turn.go's doc comment
// for how that gap is handled (optional pluggable hooks that default to the
// same "generation unavailable, degrade gracefully" behavior Python falls
// back to when those imports fail).
package wizardagent

import (
	"fmt"
	"time"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
)

// SystemPrompt ports SYSTEM_PROMPT verbatim (a Go format template using
// %s for {date}, filled by systemPromptFor). HubSpot Portal number is
// hardcoded here exactly as in the Python source (not templated from
// PortalID) — see the "HubSpot Portal: 8112310" literal below, kept
// unchanged for 1:1 fidelity even though it duplicates Agent.PortalID.
const SystemPrompt = `You are an email staging assistant for Linux Foundation marketing operations.
You stage HubSpot marketing emails from event URLs through a 3-phase flow:

PHASE 1 - PLAN: User provides an event/campaign URL.
  1. Call fetch_url to extract event name, dates, organization, description from the URL.
  2. From those details, infer: brand (HubSpot brand name), email type, and email suffix.
  3. Call lookup_brand_history to get sender settings, send list, suppression lists.
  4. Build and present a complete Email Staging Plan — see format rules below.
  5. MESSAGING STRATEGY: After building the plan, call get_variant_strategies to see
     available messaging approaches (value-focused, urgency, social proof, etc.).
     Recommend one variant strategy based on the stage and audience, then ask the user
     if they want to use a different variant.

PHASE 2 - STAGE: User approves the plan (may provide missing fields, optional variant choice).
  1. If user chose a different variant, call select_template_variant with the variant_id.
  2. Call clone_email with the correct name.
  3. Call update_email_settings to apply from name, from address, email type, suppression lists.
  4. Return the HubSpot draft URL and ask for content.

PHASE 3 - CONTENT: User provides content (Google Doc URL, HTML, or text).
  1. Call fetch_content to convert to clean email HTML.
  2. Call update_email_content to update the email body.
  3. Return the final summary with draft link.

Plan format rules (STRICTLY follow):
  - NEVER mention cloning, source emails, or templates — only show the final staged settings.
  - Present as a clean summary with two sections:
    (a) A settings table with: Email Name, From Name, From Address, Email Type, Subject, Preview Text, Send Date
    (b) Audience section showing: Send List (with contact count if available), Suppression Lists
  - Mark fields that need user input as [REQUIRED — provide below]
  - Add a short paragraph summary at the top describing what will be staged.
  - After the plan table, ask ONLY for the specific missing fields.

Email naming convention:
  "<YY>Q<N> - <Brand> - <EventName> - <Suffix>"
  Examples: "26Q2 - CNCF - KubeCon EU - Invite", "26Q2 - OpenSSF - Newsletter - June"
  Quarter: Q1=Jan-Mar, Q2=Apr-Jun, Q3=Jul-Sep, Q4=Oct-Dec
  Suffix: Invite / Last Chance / Newsletter / Update / Reminder

Messaging Variants:
  Each marketing stage (Event Announcement, Registration Launch, etc.) has multiple
  messaging variants available (e.g., "value-focused", "urgency-focused", "social-proof").
  When you detect a stage, recommend a variant strategy, and the user can select it.
  Always call get_variant_strategies(stage_name) to see available options.

Best-Practice Templates:
  Proven B2B event email templates are available from ArgoCon/KeycloakCon analysis.
  These templates have documented open rates (45-52%%) and CTR (10-22%%).
  TEMPLATE TYPES:
    - B2B_Event_Announcement: Schedule/speaker launches (45%% open rate)
    - B2B_Speaker_Conversion: Speaker to sponsor conversion (52%% open rate)
    - B2B_Strategic_Close: Multi-event deals with pricing (48%% open rate)
    - B2B_Rapid_Close: Existing accounts, quick close (35%% open rate, 22%% CTR)
    - B2B_Registration_Launch: Registration/CFP with urgency (40%% open rate)

  IMPORTANT: In the PLAN phase, recommend the matching best-practice template
  with quality rating and expected performance metrics. Show the user WHICH
  template structure they should follow for this campaign type.

Safety rules (never violate):
  - NEVER delete, archive, or send any email or list.
  - NEVER modify any existing HubSpot list.
  - NEVER call update_email_settings or update_email_content on any email
    except the one created in the current session.
  - Always keep emails in DRAFT state.

Current date: %s
HubSpot Portal: 8112310
`

// systemPromptFor ports SYSTEM_PROMPT.format(date=datetime.now().strftime("%Y-%m-%d")).
func systemPromptFor(now time.Time) string {
	return fmt.Sprintf(SystemPrompt, now.Format("2006-01-02"))
}

// Tools ports TOOLS verbatim — the 11 Anthropic tool schemas shared by every
// agentic turn.
var Tools = []domain.ToolDef{
	{
		Name:        "lookup_brand_history",
		Description: "Look up the most recently sent HubSpot email for a brand. Returns from name, from address, suppression list IDs, email type, and last email ID. Always call this first.",
		InputSchema: map[string]any{
			"type": "object",
			"properties": map[string]any{
				"brand_name":      map[string]any{"type": "string"},
				"email_type_hint": map[string]any{"type": "string", "description": "Optional: newsletter, event_invite, transactional"},
			},
			"required": []any{"brand_name"},
		},
	},
	{
		Name:        "clone_email",
		Description: "Clone a HubSpot email with a new name. Returns new email ID and draft URL.",
		InputSchema: map[string]any{
			"type": "object",
			"properties": map[string]any{
				"source_email_id": map[string]any{"type": "string"},
				"clone_name":      map[string]any{"type": "string"},
			},
			"required": []any{"source_email_id", "clone_name"},
		},
	},
	{
		Name:        "update_email_settings",
		Description: "Update email subject, preview text, from name/address, suppression list IDs, send list ID, email type.",
		InputSchema: map[string]any{
			"type": "object",
			"properties": map[string]any{
				"email_id":             map[string]any{"type": "string"},
				"subject":              map[string]any{"type": "string"},
				"preview_text":         map[string]any{"type": "string"},
				"from_name":            map[string]any{"type": "string"},
				"from_address":         map[string]any{"type": "string"},
				"suppression_list_ids": map[string]any{"type": "array", "items": map[string]any{"type": "string"}},
				"send_list_id":         map[string]any{"type": "string"},
				"email_type":           map[string]any{"type": "string"},
			},
			"required": []any{"email_id"},
		},
	},
	{
		Name:        "update_email_content",
		Description: "Replace the email body with HTML. Auto-handles html_body and widget-module templates.",
		InputSchema: map[string]any{
			"type": "object",
			"properties": map[string]any{
				"email_id":     map[string]any{"type": "string"},
				"html_content": map[string]any{"type": "string"},
			},
			"required": []any{"email_id", "html_content"},
		},
	},
	{
		Name:        "fetch_content",
		Description: "Convert a Google Doc URL, raw HTML, or plain text into clean email HTML.",
		InputSchema: map[string]any{
			"type":       "object",
			"properties": map[string]any{"content_input": map[string]any{"type": "string"}},
			"required":   []any{"content_input"},
		},
	},
	{
		Name:        "search_hubspot_lists",
		Description: "Search HubSpot contact lists by name.",
		InputSchema: map[string]any{
			"type":       "object",
			"properties": map[string]any{"search_term": map[string]any{"type": "string"}},
			"required":   []any{"search_term"},
		},
	},
	{
		Name: "fetch_url",
		Description: "Fetch an event or campaign URL and extract: event_name, brand_name, location, " +
			"event_dates, description. Always call this first when given a URL.",
		InputSchema: map[string]any{
			"type":       "object",
			"properties": map[string]any{"url": map[string]any{"type": "string"}},
			"required":   []any{"url"},
		},
	},
	{
		Name: "search_emails_for_event",
		Description: "Search HubSpot for the most recently sent email matching a brand + event name. " +
			"Filters by short_brand_name (e.g. 'LF', 'CNCF') and scores by event_name keywords. " +
			"Finds the same event's previous email for pre-populating settings.",
		InputSchema: map[string]any{
			"type": "object",
			"properties": map[string]any{
				"brand_name":       map[string]any{"type": "string", "description": "Full brand name"},
				"event_name":       map[string]any{"type": "string", "description": "Canonical event name"},
				"location":         map[string]any{"type": "string", "description": "Location hint (optional)"},
				"short_brand_name": map[string]any{"type": "string", "description": "Short brand code, e.g. LF, CNCF, PTF"},
				"event_short_name": map[string]any{"type": "string", "description": "Short event name, e.g. OSS Japan, KubeCon EU"},
				"email_type":       map[string]any{"type": "string", "description": "Email suffix hint: Invite, Last Chance, Newsletter, Reminder, Update"},
			},
			"required": []any{"brand_name", "event_name"},
		},
	},
	{
		Name: "get_variant_strategies",
		Description: "Get available messaging variant strategies for a marketing stage. " +
			"Returns list of variants with id, label, and strategy description. " +
			"Call this after detecting the event stage to recommend a variant to the user.",
		InputSchema: map[string]any{
			"type": "object",
			"properties": map[string]any{
				"stage_name": map[string]any{"type": "string", "description": "Marketing stage (e.g., 'Event Announcement', 'Registration Launch', 'Final Countdown')"},
			},
			"required": []any{"stage_name"},
		},
	},
	{
		Name: "select_template_variant",
		Description: "Select a specific messaging variant for a stage. " +
			"Call this when the user chooses a different variant from the recommended one.",
		InputSchema: map[string]any{
			"type": "object",
			"properties": map[string]any{
				"stage_name": map[string]any{"type": "string", "description": "Marketing stage"},
				"variant_id": map[string]any{"type": "string", "description": "Variant ID (e.g., 'v1_value_focused', 'v2_urgency_focused')"},
				"reason":     map[string]any{"type": "string", "description": "Why this variant was selected (for logging)"},
			},
			"required": []any{"stage_name", "variant_id"},
		},
	},
	{
		Name: "get_recommended_template",
		Description: "Get the best-practice B2B template recommendation for a campaign type. " +
			"Returns template key, quality rating (1-5 stars), expected open rate, CTR, and strategy. " +
			"Call this in PLAN phase to show which best-practice template to follow.",
		InputSchema: map[string]any{
			"type": "object",
			"properties": map[string]any{
				"campaign_type": map[string]any{"type": "string", "description": "Campaign type: announcement, speaker_conversion, multi_event_deal, existing_account_close, or registration_launch"},
			},
			"required": []any{"campaign_type"},
		},
	},
	{
		Name: "get_template_by_key",
		Description: "Get a best-practice template by its key (e.g., 'B2B_Event_Announcement'). " +
			"Returns the full template with subject, preheader, body, and placeholders. " +
			"Use this in CONTENT phase when creating Variant B to get the template to fill.",
		InputSchema: map[string]any{
			"type": "object",
			"properties": map[string]any{
				"template_key": map[string]any{"type": "string", "description": "Template key (e.g., 'B2B_Event_Announcement', 'B2B_Speaker_Conversion')"},
			},
			"required": []any{"template_key"},
		},
	},
}

// Agent bundles the dependencies every wizard turn needs — the Go
// equivalent of Python's module-level imports (hubspot_tools, content_tools,
// llm_gateway, email_templates, ai_email_templates, event_brands,
// stage_detector). All fields except Emails/Lists/LLM/Scraper are optional;
// nil-checked at each call site exactly where the corresponding Python
// capability degrades gracefully (see CLI/VariantBGen/Analyzer doc comments
// on their call sites).
type Agent struct {
	Emails  domain.HubSpotEmailClient
	Lists   domain.HubSpotListClient
	LLM     domain.LLMGateway
	Scraper domain.EventPageScraper

	// CLI is used only by FetchAsanaTaskViaMCP (ports fetch_asana_task_via_mcp).
	// May be nil — see that function's doc comment.
	CLI domain.CLISkillRunner

	// PortalID is HUBSPOT_PORTAL_ID, used to build draft-URL links exactly as
	// hubspot_tools does (e.g. clone_turn's variant_b_draft_url).
	PortalID string

	// AnthropicAPIKeySet mirrors the Python `bool(ANTHROPIC_API_KEY)` check
	// content_turn uses to append a "template-only" warning line when no key
	// is configured.
	AnthropicAPIKeySet bool

	// VariantBGen / Analyzer are optional hooks standing in for two Python
	// sibling modules that were never ported to Go (generate_ai_content.py,
	// analyze_email_content.py) — see content_turn.go's doc comment for the
	// full rationale. Leaving them nil reproduces Python's own fallback
	// behavior when those imports fail.
	VariantBGen VariantBGenerator
	Analyzer    ContentAnalyzer

	// Now returns the current time; defaults to time.Now when nil. Exists so
	// tests can pin "today" the way date-aware prompt text depends on.
	Now func() time.Time
}

// New builds an Agent from its required dependencies.
func New(emails domain.HubSpotEmailClient, lists domain.HubSpotListClient, llm domain.LLMGateway, scraper domain.EventPageScraper, portalID string) *Agent {
	return &Agent{Emails: emails, Lists: lists, LLM: llm, Scraper: scraper, PortalID: portalID}
}

func (a *Agent) now() time.Time {
	if a.Now != nil {
		return a.Now()
	}
	return time.Now()
}
