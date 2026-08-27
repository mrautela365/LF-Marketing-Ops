// Package discovery ports audience_builder/discovery_agent.py and
// discovery_tools.py: a read-only agent that finds HubSpot lists already
// existing for an event and classifies them into 6 signal buckets. It
// never creates or modifies a HubSpot list. Reuses audiencetools.Toolkit's
// web_fetch/HubSpot-search/Snowflake/reference-file implementations by
// composition rather than reimplementing them (mirrors discovery_tools.py
// importing audience_tools directly), and keeps its own job store,
// completely separate from audiencetools.Service's.
package discovery

import (
	"context"
	"encoding/json"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/audiencetools"
)

// execute ports _discovery_execute: dispatches one tool call by name
// against the shared audiencetools.Toolkit's read-only methods, plus the
// present_discovered_lists no-op. Unknown tool names (in particular the 3
// write tools discovery's schema never advertises) fall through to the
// same {"error": "Unknown tool: <name>"} shape Python returns.
func execute(ctx context.Context, tk *audiencetools.Toolkit, name string, input map[string]any) string {
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
	case "snowflake_query":
		result = tk.SnowflakeQuery(strOf(input["sql"]))
	case "read_reference_file":
		result = tk.ReadReferenceFile(strOf(input["filename"]))
	case "present_discovered_lists":
		result = presentDiscoveredLists(input)
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

// presentDiscoveredLists ports present_discovered_lists — a no-op; the
// agent loop's on_event handler intercepts this tool call by name and
// emits the structured "discovered" SSE frame from there.
func presentDiscoveredLists(input map[string]any) map[string]any {
	lists, _ := input["lists"].([]any)
	uncertain, _ := input["uncertain"].([]any)
	return map[string]any{"presented": len(lists) + len(uncertain)}
}

func strOf(v any) string {
	s, _ := v.(string)
	return s
}

func sliceOf(v any) []any {
	s, _ := v.([]any)
	return s
}

func mapOf(v any) map[string]any {
	m, _ := v.(map[string]any)
	return m
}
