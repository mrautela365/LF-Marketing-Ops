package wizardagent

import (
	"context"
	"fmt"
	"strings"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
)

// toDomainMessages converts session-scoped model.AgentMessage into the
// llm_port's domain.Message shape RunAgent actually consumes.
func toDomainMessages(messages []model.AgentMessage) []domain.Message {
	out := make([]domain.Message, len(messages))
	for i, m := range messages {
		out[i] = domain.Message{Role: m.Role, Content: m.Content}
	}
	return out
}

func fromDomainMessages(messages []domain.Message) []model.AgentMessage {
	out := make([]model.AgentMessage, len(messages))
	for i, m := range messages {
		out[i] = model.AgentMessage{Role: m.Role, Content: m.Content}
	}
	return out
}

// RunTurn ports run_turn(messages, user_message) -> (text, messages). It
// appends userMessage as a new "user" turn, runs the tool-calling agentic
// loop (max 8 steps, 4096 max tokens, exactly as Python), and returns the
// final assistant text plus the updated message history.
//
// Note: under the Claude-CLI LLMGateway backend, RunAgent's returned
// history only appends the final assistant answer — tool-call/tool-result
// exchanges are not persisted into the message list (see
// dispatch/llm_claude_cli.go). This mirrors a real limitation of that
// backend, not a bug introduced by this port; extract.go's message-scanning
// helpers are written defensively for a future richer backend but may find
// nothing under the CLI backend today.
func (a *Agent) RunTurn(ctx context.Context, session *model.SessionState, messages []model.AgentMessage, userMessage string) (string, []model.AgentMessage, error) {
	system := systemPromptFor(a.now())
	convo := append(append([]model.AgentMessage{}, messages...), model.AgentMessage{Role: "user", Content: userMessage})

	executeTool := func(name string, input map[string]any) string {
		return a.executeTool(ctx, session, name, input)
	}

	text, updated, err := a.LLM.RunAgent(ctx, toDomainMessages(convo), system, Tools, executeTool, domain.RunAgentOptions{
		MaxTokens: 4096,
		MaxSteps:  8,
	})
	if err != nil {
		return "", nil, err
	}
	return text, fromDomainMessages(updated), nil
}

// ChatTurn ports chat_turn(session, message) = run_turn(session.messages, message).
func (a *Agent) ChatTurn(ctx context.Context, session *model.SessionState, message string) (string, []model.AgentMessage, error) {
	return a.RunTurn(ctx, session, session.Messages, message)
}

// PlanTurn ports plan_turn(session, url) — builds the structured-plan
// prompt (fetch the URL, infer brand/type/suffix, look up brand history,
// present the plan in the required markdown format) and runs it through
// RunTurn.
func (a *Agent) PlanTurn(ctx context.Context, session *model.SessionState, url string) (string, []model.AgentMessage, error) {
	prompt := buildPlanPrompt(url)
	return a.RunTurn(ctx, session, session.Messages, prompt)
}

// buildPlanPrompt ports plan_turn's `prompt` f-string verbatim (agent.py
// lines ~1593-1669) — the STEP 1-5 instruction block, the BEST-PRACTICE
// TEMPLATE SECTION note, and the exact four-section "Email Staging Plan"
// markdown template (Stage & Content Overview, Settings, Audience,
// Messaging Variant), byte-for-byte, only substituting the URL. An earlier
// revision of this function paraphrased this block; this is now a faithful
// verbatim port.
func buildPlanPrompt(url string) string {
	var b strings.Builder
	fmt.Fprintf(&b, "The user wants to stage an email for this event URL:\n%s\n\n", url)
	b.WriteString("CRITICAL — follow this order STRICTLY:\n")
	b.WriteString("  STEP 1: Call fetch_url to extract event_name, brand_name, location, event_dates.\n")
	b.WriteString("  STEP 2: Call search_emails_for_event(brand_name, event_name, location).\n")
	b.WriteString("          If event_match=False, also call lookup_brand_history as fallback.\n")
	b.WriteString("  STEP 3: Detect the marketing stage from event details.\n")
	b.WriteString("  STEP 4: Map stage to campaign_type, then call get_recommended_template(campaign_type).\n")
	b.WriteString("  STEP 5: ONLY AFTER steps 1-4 are done, write the full plan including template recommendation.\n\n")
	b.WriteString("BEST-PRACTICE TEMPLATE SECTION (add to plan after Stage & Content Overview):\n")
	b.WriteString("  After detecting stage in STEP 3, call get_recommended_template() to get:\n")
	b.WriteString("    - Template name (e.g., 'B2B_Event_Announcement')\n")
	b.WriteString("    - Quality rating (1-5 stars, shown as ★★★★★)\n")
	b.WriteString("    - Expected open rate and CTR from ArgoCon data\n")
	b.WriteString("    - Marketing strategy (e.g., 'Build excitement + relationship focus + multiple CTAs')\n")
	b.WriteString("  \n")
	b.WriteString("  Include a new section in the plan:\n")
	b.WriteString("    ### VARIANT B (Best-Practice Template) — Auto-Generated\n")
	b.WriteString("    Template: [Template Name] (★★★★★)\n")
	b.WriteString("    Expected Performance: [XX]% open rate, [XX]% CTR\n")
	b.WriteString("    Strategy: [Strategy from template]\n")
	b.WriteString("    Source: ArgoCon + KeycloakCon Japan 2026\n")
	b.WriteString("    \n")
	b.WriteString("    This variant will be automatically generated after you provide content for Variant A.\n")
	b.WriteString("    You can review both before sending.\n\n")
	b.WriteString("⚠️  DO NOT write any plan content before completing STEP 1 and STEP 2.\n")
	b.WriteString("⚠️  DO NOT say 'the plan above', 'as shown above', or 'presented above'.\n")
	b.WriteString("⚠️  Your FINAL message must contain the COMPLETE plan written from scratch.\n\n")
	b.WriteString("Your final response MUST contain the full plan in this EXACT format ")
	b.WriteString("(all four sections — Stage & Content Overview FIRST, then Settings, then Audience):\n\n")
	b.WriteString("---\n")
	b.WriteString("## Email Staging Plan — [Event Name]\n\n")
	b.WriteString("One sentence: what event, what type of email, which stage.\n\n")
	b.WriteString("### Stage & Content Overview\n\n")
	b.WriteString("| Field | Value |\n")
	b.WriteString("|---|---|\n")
	b.WriteString("| **Current Stage** | [stage name] ([funnel] — [N] days to event) |\n")
	b.WriteString("| **Stage Goal** | [what this email is trying to achieve] |\n")
	b.WriteString("| **Email Type** | [Invite / Last Chance / Reminder / Newsletter / etc.] |\n")
	b.WriteString("| **CTA** | [call-to-action label] |\n")
	b.WriteString("| **Event Date** | [event date] |\n")
	b.WriteString("| **Content Reference** | [name of previous email used as style reference, or 'Stage template'] |\n\n")
	b.WriteString("**What will be included in the generated email:**\n")
	b.WriteString("- **Speakers**: [list ALL confirmed speaker names, or 'To be announced']\n")
	b.WriteString("- **Sponsors / Partners**: [list ALL confirmed sponsor names, or 'None found']\n")
	b.WriteString("- **Topics / Tracks**: [list]\n")
	b.WriteString("- **Email Sections**: [intro paragraph → [stage-specific content] → speaker highlights → ")
	b.WriteString("registration CTA → closing]\n\n")
	b.WriteString("### Settings\n\n")
	b.WriteString("| Field | Value |\n")
	b.WriteString("|---|---|\n")
	b.WriteString("| **Email Name** | `26QN - Brand - Event - Suffix` |\n")
	b.WriteString("| **From Name** | (from brand history) |\n")
	b.WriteString("| **From Address** | (from brand history) |\n")
	b.WriteString("| **Subject Line** | *(auto-generated — shown below the plan)* |\n")
	b.WriteString("| **Preview Text** | *(auto-generated — shown below the plan)* |\n\n")
	b.WriteString("### Audience\n\n")
	b.WriteString("| | |\n")
	b.WriteString("|---|---|\n")
	b.WriteString("| **Send List** | (list name and contact count from brand history) |\n")
	b.WriteString("| **Suppression Lists** | (all suppression list IDs/names from brand history) |\n\n")
	b.WriteString("### Messaging Variant (Optional)\n\n")
	b.WriteString("We have multiple messaging strategies available for this stage. Each variant emphasizes\n")
	b.WriteString("different selling points (value vs urgency vs social proof). You can accept the recommended\n")
	b.WriteString("one or choose a different approach:\n\n")
	b.WriteString("**Available variants:**\n")
	b.WriteString("[The agent will call get_variant_strategies(stage) to show available options here]\n\n")
	b.WriteString("- **Recommended**: [variant_id] — [reason]\n")
	b.WriteString("- To choose a different variant, say: \"Use variant [variant_id]\" in your response.\n")
	b.WriteString("- If you're happy with the recommended variant, just proceed to the next step.\n\n")
	b.WriteString("---\n\n")
	b.WriteString("When ready, say \"Approve\" or \"Let's go\" to proceed to the next step.\n")
	b.WriteString("Optional: Say \"Use variant [variant_id]\" to select a different messaging approach.\n\n")
	b.WriteString("Do NOT ask for subject line, preview text, send date, or any other inputs.\n")
	b.WriteString("Do NOT mention cloning, source emails, or templates anywhere.\n")
	b.WriteString("Do NOT say 'the plan above' or 'as shown above' — write everything in this single response.")
	return b.String()
}
