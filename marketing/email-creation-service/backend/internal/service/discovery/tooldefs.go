package discovery

import (
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/audiencetools"
)

// readOnlyToolNames mirrors discovery_tools.py's _READ_ONLY_TOOL_NAMES —
// deliberately excludes hubspot_create_list / hubspot_update_list_filters /
// hubspot_get_event_types: discovery must never create or modify HubSpot
// state.
var readOnlyToolNames = map[string]bool{
	"web_fetch":                true,
	"hubspot_search_campaigns": true,
	"hubspot_search_lists":     true,
	"hubspot_get_list":         true,
	"snowflake_query":          true,
	"read_reference_file":      true,
}

// ToolDefs ports discovery_tools.py's TOOL_DEFS_OPENAI: the read-only subset
// of audiencetools.ToolDefs() (reused by name — same description/schema
// text, not re-typed) plus this package's own present_discovered_lists def.
func ToolDefs() []domain.ToolDef {
	base := audiencetools.ToolDefs()
	defs := make([]domain.ToolDef, 0, len(readOnlyToolNames)+1)
	for _, d := range base {
		if readOnlyToolNames[d.Name] {
			defs = append(defs, d)
		}
	}
	defs = append(defs, presentDiscoveredListsDef())
	return defs
}

// presentDiscoveredListsDef ports discovery_tools.py's
// _PRESENT_DISCOVERED_LISTS_DEF verbatim (description text and schema
// copied byte-for-byte).
func presentDiscoveredListsDef() domain.ToolDef {
	return domain.ToolDef{
		Name: "present_discovered_lists",
		Description: "Present the final set of discovered HubSpot lists for user selection. Call this " +
			"exactly ONCE, after you have investigated the event and classified every relevant " +
			"existing list into one of the 6 signal buckets (or into 'uncertain' if it doesn't " +
			"confidently fit). This is a read-only discovery pass — you have no tool that can " +
			"create or modify a HubSpot list, so do not attempt to.",
		InputSchema: map[string]any{
			"type": "object",
			"properties": map[string]any{
				"brand_short": map[string]any{
					"type":        "string",
					"description": "The event's short brand/foundation code identified in STEP 1 (e.g. CNCF, PyTorch, Hyperledger, LF) — reused to look up brand-scoped suppression lists.",
				},
				"event_name": map[string]any{
					"type":        "string",
					"description": "The event's proper name identified in STEP 1 — reused to look up any pre-existing suppression list for this specific event and to find what was last sent for it.",
				},
				"lists": map[string]any{
					"type":        "array",
					"description": "Every existing HubSpot list confidently matched to one of the 6 signals.",
					"items": map[string]any{
						"type": "object",
						"properties": map[string]any{
							"list_id": map[string]any{"type": "string"},
							"name":    map[string]any{"type": "string"},
							"signal": map[string]any{
								"type": "string",
								"enum": []string{
									"project_opt_in",
									"lf_newsletter_opt_in",
									"event_registration",
									"education_enrollment",
									"page_view",
									"event_speakers",
								},
							},
							"size":   map[string]any{"type": "integer", "description": "Membership count, if known."},
							"reason": map[string]any{"type": "string", "description": "Short justification tying this list to the signal."},
							"list_type": map[string]any{
								"type":        "string",
								"description": "The list's real processingType field from hubspot_get_list, verbatim (e.g. DYNAMIC, MANUAL, SNAPSHOT). Do not guess — omit if you didn't call hubspot_get_list on it.",
							},
							"scope": map[string]any{
								"type":        "string",
								"enum":        []string{"current", "past", "current_past"},
								"description": "Only meaningful when signal is 'event_speakers' — which edition(s) of the event this speaker list actually covers, per STEP 3 rule 6. Omit for every other signal.",
							},
						},
						"required": []string{"list_id", "name", "signal"},
					},
				},
				"uncertain": map[string]any{
					"type":        "array",
					"description": "Lists that look event-relevant but don't confidently map to one of the 5 signals.",
					"items": map[string]any{
						"type": "object",
						"properties": map[string]any{
							"list_id":   map[string]any{"type": "string"},
							"name":      map[string]any{"type": "string"},
							"size":      map[string]any{"type": "integer"},
							"reason":    map[string]any{"type": "string"},
							"list_type": map[string]any{"type": "string", "description": "Real processingType from hubspot_get_list, if known."},
						},
						"required": []string{"list_id", "name"},
					},
				},
			},
			"required": []string{"lists", "uncertain"},
		},
	}
}
