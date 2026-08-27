package wizardagent

import (
	"context"
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strings"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/emailtemplates"
)

// jsonError mirrors json.dumps({"error": msg}) used throughout _execute_tool.
func jsonError(msg string) string {
	b, _ := json.Marshal(map[string]string{"error": msg})
	return string(b)
}

// decodeJSONMap decodes one of executeTool's JSON-string results into a
// map, for callers (like clone_turn) that bypass the LLM and need to read
// a tool result directly.
func decodeJSONMap(s string) (map[string]any, error) {
	var m map[string]any
	if err := json.Unmarshal([]byte(s), &m); err != nil {
		return nil, err
	}
	return m, nil
}

// formatAllowedSet renders a Go map's keys the way Python's f"{allowed_ids}"
// renders a set literal closely enough for an error message — exact
// character-for-character set repr isn't load-bearing here, only that the
// allowed IDs are visible to the caller. Sorted for determinism.
func formatAllowedSet(allowed map[string]bool) string {
	ids := make([]string, 0, len(allowed))
	for id := range allowed {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	return "{" + strings.Join(ids, ", ") + "}"
}

// claudeText ports _claude_text — a thin wrapper over llm_gateway.complete_text.
func (a *Agent) claudeText(ctx context.Context, prompt string, maxTokens, timeoutSeconds, idleTimeoutSeconds int) (string, error) {
	return a.LLM.CompleteText(ctx, prompt, domain.CompleteTextOptions{
		MaxTokens:          maxTokens,
		TimeoutSeconds:     timeoutSeconds,
		IdleTimeoutSeconds: idleTimeoutSeconds,
	})
}

// formatABTestComparison ports _format_ab_test_comparison verbatim — a
// box-drawing-character comparison of the two variants shown to the user
// after clone_turn finishes staging both emails.
func formatABTestComparison(variantAInfo, variantBInfo map[string]any) string {
	get := func(m map[string]any, key, def string) string {
		if v, ok := m[key]; ok && v != nil {
			if s, ok := v.(string); ok && s != "" {
				return s
			}
		}
		return def
	}

	aSubject := get(variantAInfo, "subject", "(none)")
	aType := get(variantAInfo, "type", "User-Created Content")
	bSubject := get(variantBInfo, "subject", "(none)")
	bTemplate := get(variantBInfo, "template_key", "(none)")
	bQuality := get(variantBInfo, "quality_rating", "")

	var b strings.Builder
	b.WriteString("\n┌─────────────────────────────────────────────────────────┐\n")
	b.WriteString("│  A/B TEST COMPARISON                                     │\n")
	b.WriteString("├─────────────────────────────────────────────────────────┤\n")
	fmt.Fprintf(&b, "│  Variant A (%s)\n", aType)
	fmt.Fprintf(&b, "│    Subject: %s\n", aSubject)
	b.WriteString("│\n")
	fmt.Fprintf(&b, "│  Variant B (Best-Practice Template: %s)\n", bTemplate)
	fmt.Fprintf(&b, "│    Subject: %s\n", bSubject)
	if bQuality != "" {
		fmt.Fprintf(&b, "│    Quality Rating: %s/5\n", bQuality)
	}
	b.WriteString("└─────────────────────────────────────────────────────────┘\n")
	return b.String()
}

// fillSimpleTemplatePlaceholders ports _fill_template_placeholders — the
// small 4-placeholder filler used by clone_turn's best-practice-template
// preview text, distinct from aiemailtemplates.FillTemplatePlaceholders'
// larger bracket-style set used by the AI Template generator.
func fillSimpleTemplatePlaceholders(templateText string, eventData map[string]any) string {
	get := func(key, def string) string {
		if v, ok := eventData[key]; ok && v != nil {
			if s, ok := v.(string); ok && s != "" {
				return s
			}
		}
		return def
	}
	result := templateText
	result = strings.ReplaceAll(result, "[Event Name]", get("event_name", "Event"))
	result = strings.ReplaceAll(result, "[Dates]", get("event_dates", "TBD"))
	result = strings.ReplaceAll(result, "[City]", get("location", "TBD"))
	result = strings.ReplaceAll(result, "[Date]", get("event_dates", "TBD"))
	return result
}

// getVariantSubjectPreview ports _get_variant_subject_preview — resolves a
// stage/variant's raw subject/preheader templates and fills placeholders
// with event_data, for display in the plan.
func getVariantSubjectPreview(stageName, variantID string, eventData map[string]any) (subject, preview string, ok bool) {
	v, found := emailtemplates.GetTemplateVariant(stageName, variantID)
	if !found {
		return "", "", false
	}
	return fillSimpleTemplatePlaceholders(v.Subject, eventData), fillSimpleTemplatePlaceholders(v.Preheader, eventData), true
}

// recommendBestPracticeTemplateReason ports _recommend_best_practice_template
// — wraps emailtemplates.RecommendBestPracticeTemplate and adds a hardcoded
// human-readable reason for the recommendation, keyed by campaign type.
func recommendBestPracticeTemplateReason(campaignType string, campaignContext map[string]any) (*emailtemplates.RecommendedTemplate, string, bool) {
	rec, ok := emailtemplates.RecommendBestPracticeTemplate(campaignType)
	if !ok {
		return nil, "", false
	}

	reasonMap := map[string]string{
		"announcement":           "Schedule/speaker launches perform best with a clean announcement structure (45% open rate).",
		"speaker_conversion":     "Speaker-to-sponsor conversion emails benefit from social proof and a direct upgrade CTA (52% open rate).",
		"multi_event_deal":       "Multi-event strategic deals need pricing clarity and urgency for the close (48% open rate).",
		"existing_account_close": "Existing accounts respond to a rapid, low-friction close message (35% open rate, 22% CTR).",
		"registration_launch":    "Registration/CFP launches convert best with urgency-forward messaging (40% open rate).",
	}
	reason := reasonMap[campaignType]
	if reason == "" {
		reason = "Recommended based on documented performance for this campaign type."
	}
	return rec, reason, true
}

// compareWithSimilarEmails ports _compare_with_similar_emails — surfaces the
// best-practice template match for a stage/campaign context as a
// user-facing comparison string. This is a thin formatting wrapper; the
// underlying data all comes from emailtemplates.
func compareWithSimilarEmails(stageName string, campaignContext map[string]any) string {
	rec, reason, ok := recommendBestPracticeTemplateReason(stageName, campaignContext)
	if !ok || rec.Template == nil {
		return fmt.Sprintf("No best-practice template comparison available for stage %q.", stageName)
	}
	return fmt.Sprintf(
		"Best-practice comparison for %q:\n  Template: %s\n  Quality: %d/5\n  Source: %s\n  Why: %s",
		stageName, rec.Key, rec.QualityRating, rec.Source, reason,
	)
}

// stageVariantRecommendation is one entry of the hardcoded
// _recommend_variant_strategy lookup table.
type stageVariantRecommendation struct {
	VariantID string
	Reason    string
}

// variantStrategyByStage ports the hardcoded dict inside
// _recommend_variant_strategy verbatim.
var variantStrategyByStage = map[string]stageVariantRecommendation{
	"Event Announcement":               {"v1_value_focused", "Lead with value to build initial interest"},
	"CFP Launch":                       {"v2_urgency_focused", "CFP deadlines benefit from urgency framing"},
	"Registration Launch":              {"v1_value_focused", "Early registration messaging should emphasize value"},
	"Co-Located Events + CFP Reminder": {"v2_urgency_focused", "Reminders perform best with urgency"},
	"DEI & Travel Fund":                {"v1_value_focused", "Value-focused framing suits DEI/travel fund messaging"},
	"Schedule Announcement":            {"v1_value_focused", "Schedule reveals work well as a value highlight"},
	"Final Countdown":                  {"v2_urgency_focused", "Final countdown is inherently urgency-driven"},
	"Event Week":                       {"v2_urgency_focused", "Event week messaging is time-sensitive"},
	"Thank You + Survey":               {"v1_value_focused", "Thank-you messaging should stay value/appreciation focused"},
	"Content & Recordings Release":     {"v1_value_focused", "Recordings releases are a value-add announcement"},
	"Next Event CFP Teaser":            {"v3_social_proof", "Teasers benefit from social proof of the prior event"},
	"Community Nurture":                {"v3_social_proof", "Nurture messaging works well with social proof"},
}

// recommendVariantStrategy ports _recommend_variant_strategy verbatim,
// including its default fallback for unmapped stages/audiences.
func recommendVariantStrategy(stageName string, daysToEvent *int, audienceType string) (variantID, reason string) {
	if rec, ok := variantStrategyByStage[stageName]; ok {
		return rec.VariantID, rec.Reason
	}
	return "v1_main", "Standard template variant"
}

// formatVariantRecommendations ports _format_variant_recommendations —
// renders every available variant strategy for a stage plus which one is
// recommended, for display in the plan.
func formatVariantRecommendations(stageName string) string {
	strategies, ok := emailtemplates.ListVariantStrategies(stageName)
	if !ok || len(strategies) == 0 {
		return fmt.Sprintf("No messaging variants available for stage %q.", stageName)
	}
	recID, recReason := recommendVariantStrategy(stageName, nil, "tech")

	var b strings.Builder
	fmt.Fprintf(&b, "Available messaging variants for %q:\n", stageName)
	for _, s := range strategies {
		marker := "  "
		if s.ID == recID {
			marker = "→ "
		}
		fmt.Fprintf(&b, "%s%s (%s): %s\n", marker, s.ID, s.Label, s.Strategy)
	}
	fmt.Fprintf(&b, "\nRecommended: %s — %s\n", recID, recReason)
	return b.String()
}

// balancedJSONBlock scans text for the first balanced-brace `{...}`
// substring, honoring string literals so braces inside quoted strings don't
// throw off the depth counter. Ports the balanced-brace JSON extraction
// technique used by generate_email_content / generate_ai_template_content
// in place of a naive first-'{'-to-last-'}' slice or a bare json.loads on
// the whole LLM response.
func balancedJSONBlock(text string) (string, bool) {
	start := strings.IndexByte(text, '{')
	if start < 0 {
		return "", false
	}
	depth := 0
	inString := false
	escaped := false
	for i := start; i < len(text); i++ {
		c := text[i]
		if inString {
			switch {
			case escaped:
				escaped = false
			case c == '\\':
				escaped = true
			case c == '"':
				inString = false
			}
			continue
		}
		switch c {
		case '"':
			inString = true
		case '{':
			depth++
		case '}':
			depth--
			if depth == 0 {
				return text[start : i+1], true
			}
		}
	}
	return "", false
}

// stripMarkdownFences removes a leading/trailing ```json ... ``` or ``` ...
// ``` fence, matching the .strip() + fence-stripping preprocessing every
// LLM-JSON call site in agent.py performs before parsing.
var fenceRe = regexp.MustCompile("(?s)^\\s*```(?:json)?\\s*(.*?)\\s*```\\s*$")

func stripMarkdownFences(s string) string {
	s = strings.TrimSpace(s)
	if m := fenceRe.FindStringSubmatch(s); m != nil {
		return strings.TrimSpace(m[1])
	}
	return s
}

// fetchAsanaTaskResult is the parsed shape fetch_asana_task_via_mcp returns
// on success.
type fetchAsanaTaskResult struct {
	EmailName    string   `json:"email_name"`
	SubtaskNames []string `json:"subtask_names"`
	Raw          map[string]any
}

// fetchAsanaTaskViaMCP ports fetch_asana_task_via_mcp. It is reachable ONLY
// when the LLM backend is the Claude Code CLI (domain.CLISkillRunner) —
// unlike every other LLM call in this package, it relies on the CLI's own
// native MCP tool integration to fetch the Asana task (no TOOL_CALL/
// TOOL_RESULT text-protocol emulation, no --strict-mcp-config; the model is
// simply trusted to use whatever Asana MCP tools it has configured and
// report back JSON). Returns (nil, false, nil) when a.CLI is nil — mirroring
// Python's behavior when the MCP call path isn't available in-process,
// which this Go port models as "capability not configured" rather than
// attempting and failing.
func (a *Agent) fetchAsanaTaskViaMCP(ctx context.Context, taskURL string) (*fetchAsanaTaskResult, bool, error) {
	if a.CLI == nil {
		return nil, false, nil
	}

	prompt := fmt.Sprintf(`Use your Asana MCP tools to fetch the task at this URL: %s

Steps:
1. Extract the task GID from the URL and fetch the task details (name, notes, custom fields).
2. Fetch the task's subtasks and list their names.
3. Fetch the task's comments/stories if that helps understand the request.
4. Respond with ONLY a JSON object (no markdown fences, no commentary) with this shape:
   {"email_name": "<a suggested email name based on the task>", "subtask_names": ["<subtask 1>", "<subtask 2>", ...], "task_notes": "<brief summary of the task notes/brief>"}

If you cannot access the task, respond with {"email_name": "", "subtask_names": [], "error": "<what went wrong>"}.`, taskURL)

	raw, success, err := a.CLI.RunCLISkill(ctx, prompt, domain.RunCLISkillOptions{TimeoutSeconds: 180})
	if err != nil {
		return nil, false, err
	}
	if !success {
		return nil, false, nil
	}

	cleaned := stripMarkdownFences(raw)
	block, ok := balancedJSONBlock(cleaned)
	if !ok {
		return nil, false, nil
	}

	var data map[string]any
	if err := json.Unmarshal([]byte(block), &data); err != nil {
		return nil, false, nil
	}

	result := &fetchAsanaTaskResult{Raw: data}
	if v, ok := data["email_name"].(string); ok {
		result.EmailName = v
	}
	if arr, ok := data["subtask_names"].([]any); ok {
		for _, item := range arr {
			if s, ok := item.(string); ok {
				result.SubtaskNames = append(result.SubtaskNames, s)
			}
		}
	}
	if result.SubtaskNames == nil {
		result.SubtaskNames = []string{}
	}
	return result, true, nil
}
