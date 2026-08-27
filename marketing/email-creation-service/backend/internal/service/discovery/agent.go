package discovery

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/audiencetools"
)

// allSignals ports ALL_SIGNALS verbatim.
var allSignals = []string{
	"project_opt_in",
	"lf_newsletter_opt_in",
	"event_registration",
	"education_enrollment",
	"page_view",
	"event_speakers",
}

// normalizeListItems ports _normalize_list_items verbatim: the model
// sometimes emits HubSpot's own camelCase keys (listId, notes) instead of
// the schema's list_id/reason — normalize so downstream code (and the
// frontend) always sees list_id/reason.
func normalizeListItems(items []any) []map[string]any {
	normalized := make([]map[string]any, 0, len(items))
	for _, raw := range items {
		item := mapOf(raw)
		if item == nil {
			continue
		}
		copyItem := make(map[string]any, len(item))
		for k, v := range item {
			copyItem[k] = v
		}
		if _, ok := copyItem["list_id"]; !ok {
			if v, ok2 := copyItem["listId"]; ok2 {
				copyItem["list_id"] = v
				delete(copyItem, "listId")
			}
		}
		if _, ok := copyItem["reason"]; !ok {
			if v, ok2 := copyItem["notes"]; ok2 {
				copyItem["reason"] = v
				delete(copyItem, "notes")
			}
		}
		if _, ok := copyItem["list_type"]; !ok {
			if v, ok2 := copyItem["listType"]; ok2 {
				copyItem["list_type"] = v
				delete(copyItem, "listType")
			}
		}
		if _, ok := copyItem["list_type"]; !ok {
			if v, ok2 := copyItem["processingType"]; ok2 {
				copyItem["list_type"] = v
				delete(copyItem, "processingType")
			}
		}
		normalized = append(normalized, copyItem)
	}
	return normalized
}

// computeMissingSignals ports _compute_missing_signals verbatim.
func computeMissingSignals(lists []map[string]any) []string {
	found := map[string]bool{}
	for _, item := range lists {
		if s, ok := item["signal"].(string); ok {
			found[s] = true
		}
	}
	missing := make([]string, 0, len(allSignals))
	for _, s := range allSignals {
		if !found[s] {
			missing = append(missing, s)
		}
	}
	return missing
}

// runDiscoveryAgent ports _run_discovery_agent verbatim: drives one
// read-only discovery run via the shared LLMGateway, intercepting
// present_discovered_lists tool calls to emit a structured "discovered" SSE
// frame and tracking the final discovered set for the terminal "done" frame.
func runDiscoveryAgent(ctx context.Context, gw domain.LLMGateway, tk *audiencetools.Toolkit, prompt string, q chan any) {
	q <- map[string]any{"type": "output", "text": "🔍 Starting discovery…"}

	discovered := map[string]any{
		"lists": []map[string]any{}, "uncertain": []map[string]any{},
		"brand_short": "", "event_name": "",
	}

	executeAndTrack := func(name string, input map[string]any) string {
		resultJSON := execute(ctx, tk, name, input)
		if name == "present_discovered_lists" {
			discovered["lists"] = normalizeListItems(sliceOf(input["lists"]))
			discovered["uncertain"] = normalizeListItems(sliceOf(input["uncertain"]))
			discovered["brand_short"] = strOf(input["brand_short"])
			discovered["event_name"] = strOf(input["event_name"])
		}
		return resultJSON
	}

	onEvent := func(ev domain.AgentEvent) {
		switch ev.Type {
		case "output":
			for _, line := range strings.Split(ev.Text, "\n") {
				if strings.TrimSpace(line) != "" {
					q <- map[string]any{"type": "output", "text": line}
				}
			}
		case "output_delta":
			if ev.Text != "" {
				q <- map[string]any{"type": "output", "text": ev.Text, "delta": true}
			}
		case "tool":
			switch ev.Name {
			case "present_discovered_lists":
				inp := ev.Input
				lists := normalizeListItems(sliceOf(inp["lists"]))
				uncertain := normalizeListItems(sliceOf(inp["uncertain"]))
				missingSignals := computeMissingSignals(lists)
				brandShort := strOf(inp["brand_short"])
				eventName := strOf(inp["event_name"])
				q <- map[string]any{"type": "output", "text": fmt.Sprintf("✅ %d list(s) discovered, %d uncertain", len(lists), len(uncertain))}
				q <- map[string]any{
					"type": "discovered", "lists": lists, "uncertain": uncertain,
					"missing_signals": missingSignals,
					"brand_short":     brandShort, "event_name": eventName,
				}
			case "snowflake_query":
				q <- map[string]any{"type": "output", "text": fmt.Sprintf("🔧 %s:\n%s", ev.Name, strOf(ev.Input["sql"]))}
			default:
				inputJSON, _ := json.Marshal(ev.Input)
				preview := string(inputJSON)
				if len(preview) > 100 {
					preview = preview[:100]
				}
				q <- map[string]any{"type": "output", "text": fmt.Sprintf("🔧 %s(%s)", ev.Name, preview)}
			}
		case "tool_result":
			text := ev.Text
			if len(text) > 200 {
				text = text[:200]
			}
			q <- map[string]any{"type": "output", "text": "   ↳ " + text}
		}
	}

	finalFrame := func(success bool) map[string]any {
		return map[string]any{
			"type": "done", "done": true, "success": success,
			"lists": discovered["lists"], "uncertain": discovered["uncertain"],
			"missing_signals": computeMissingSignals(discovered["lists"].([]map[string]any)),
			"brand_short":     discovered["brand_short"], "event_name": discovered["event_name"],
		}
	}

	messages := []domain.Message{{Role: "user", Content: prompt}}
	_, _, err := gw.RunAgent(ctx, messages, DiscoverySystem, ToolDefs(), executeAndTrack, domain.RunAgentOptions{
		MaxTokens: 16000,
		MaxSteps:  40,
		OnEvent:   onEvent,
	})
	if err != nil {
		q <- map[string]any{"type": "output", "text": fmt.Sprintf("❌ Discovery error: %v", err)}
		q <- finalFrame(false)
		return
	}
	q <- finalFrame(true)
}
