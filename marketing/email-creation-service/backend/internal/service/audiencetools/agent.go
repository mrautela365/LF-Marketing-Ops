package audiencetools

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
)

// AudienceSystem is the system prompt used for every audiencetools agent
// run (plan/build/custom-plan/custom-build) — see prompts_gen.go.
const audienceSystemPrompt = AudienceSystem

// execute ports _audience_execute: dispatches one tool call by name against
// the Toolkit and JSON-encodes the result. Unlike Python's TOOL_HANDLERS
// dict-of-lambdas, this is a plain switch over the 10 known tool names —
// same externally observable behavior (a JSON string per call, or
// {"error": "Unknown tool: <name>"} for anything else).
func (tk *Toolkit) execute(ctx context.Context, name string, input map[string]any) string {
	var result any
	switch name {
	case "web_fetch":
		result = tk.WebFetch(strOf(input["url"]))
	case "hubspot_search_campaigns":
		result = tk.HubSpotSearchCampaigns(ctx, strOf(input["query"]))
	case "hubspot_search_lists":
		result = tk.HubSpotSearchLists(ctx, strOf(input["query"]))
	case "hubspot_get_list":
		result = tk.HubSpotGetList(ctx, strOf(input["list_id"]))
	case "hubspot_create_list":
		result = tk.HubSpotCreateList(ctx, strOf(input["name"]), mapOf(input["filter_branch"]))
	case "hubspot_update_list_filters":
		result = tk.HubSpotUpdateListFilters(ctx, strOf(input["list_id"]), mapOf(input["filter_branch"]))
	case "hubspot_get_event_types":
		result = tk.HubSpotGetEventTypes(ctx)
	case "snowflake_query":
		result = tk.SnowflakeQuery(strOf(input["sql"]))
	case "read_reference_file":
		result = tk.ReadReferenceFile(strOf(input["filename"]))
	case "present_open_questions":
		result = tk.PresentOpenQuestions(sliceOf(input["questions"]))
	default:
		result = map[string]any{"error": "Unknown tool: " + name}
	}
	b, err := json.Marshal(result)
	if err != nil {
		errB, _ := json.Marshal(map[string]any{"error": err.Error()})
		return string(errB)
	}
	return string(b)
}

func strOf(v any) string {
	s, _ := v.(string)
	return s
}

func mapOf(v any) map[string]any {
	m, _ := v.(map[string]any)
	return m
}

func sliceOf(v any) []any {
	s, _ := v.([]any)
	return s
}

// runAgent ports _run_agent verbatim: drives one agentic tool-calling run
// via the shared LLMGateway, streaming events to q in the exact shapes the
// SSE consumer (audience_job_handlers.go) expects, and tracking
// hubspot_create_list / hubspot_update_list_filters results so the LAST
// list touched — guaranteed by RULE 4 in the building prompt to be the
// master list — can be reported as ground truth rather than parsed from
// free text.
func (s *Service) runAgent(ctx context.Context, prompt string, q chan any) {
	q <- map[string]any{"type": "output", "text": "🚀 Starting agent…"}

	var createdLists []map[string]any

	executeAndTrack := func(name string, input map[string]any) string {
		resultJSON := s.Toolkit.execute(ctx, name, input)
		if name == "hubspot_create_list" || name == "hubspot_update_list_filters" {
			var parsed map[string]any
			if err := json.Unmarshal([]byte(resultJSON), &parsed); err == nil {
				if id, ok := parsed["listId"]; ok && id != nil && id != "" {
					createdLists = append(createdLists, parsed)
				}
			}
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
			case "present_open_questions":
				questions := sliceOf(ev.Input["questions"])
				q <- map[string]any{"type": "output", "text": fmt.Sprintf("❓ %d open question(s) — see selection above", len(questions))}
				q <- map[string]any{"type": "question", "questions": questions}
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

	lastMasterListID := func() any {
		if len(createdLists) == 0 {
			return nil
		}
		return createdLists[len(createdLists)-1]["listId"]
	}

	messages := []domain.Message{{Role: "user", Content: prompt}}
	_, _, err := s.Gateway.RunAgent(ctx, messages, audienceSystemPrompt, ToolDefs(), executeAndTrack, domain.RunAgentOptions{
		MaxTokens: 32000,
		MaxSteps:  40,
		OnEvent:   onEvent,
	})
	if err != nil {
		q <- map[string]any{"type": "output", "text": fmt.Sprintf("❌ Agent error: %v", err)}
		q <- map[string]any{"type": "done", "done": true, "success": false, "master_list_id": lastMasterListID()}
		return
	}
	q <- map[string]any{"type": "done", "done": true, "success": true, "master_list_id": lastMasterListID()}
}
