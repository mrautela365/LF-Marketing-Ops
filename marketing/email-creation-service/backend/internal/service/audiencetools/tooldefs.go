package audiencetools

import "github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"

// fn builds one domain.ToolDef with an object-shaped InputSchema — ports
// audience_tools.py's _fn() helper. Python emits OpenAI-format tool defs and
// converts them via llm_gateway.openai_tools_to_anthropic; domain.ToolDef is
// already in the Anthropic-canonical {name, description, input_schema}
// shape, so no separate OpenAI-format intermediate or converter is needed
// here — this directly builds the canonical shape the gateway expects.
func fn(name, description string, properties map[string]any, required []string) domain.ToolDef {
	return domain.ToolDef{
		Name:        name,
		Description: description,
		InputSchema: map[string]any{
			"type":       "object",
			"properties": properties,
			"required":   required,
		},
	}
}

// ToolDefs ports TOOL_DEFS_OPENAI's 10 entries verbatim (description text
// copied byte-for-byte from audience_tools.py).
func ToolDefs() []domain.ToolDef {
	return []domain.ToolDef{
		fn("web_fetch",
			"Fetch the text content of any URL. Use to scrape event pages.",
			map[string]any{"url": map[string]any{"type": "string", "description": "The URL to fetch"}},
			[]string{"url"}),

		fn("hubspot_search_campaigns",
			"Search HubSpot marketing emails by keyword (name or subject). Use to find prior sends for an event. "+
				"Query broad first (event series name alone, e.g. 'Open Source Summit') — this returns every edition/"+
				"country in one call. Only narrow the query if the broad one returns nothing; don't guess quarter/"+
				"country/year permutations one at a time.",
			map[string]any{"query": map[string]any{"type": "string", "description": "Search keyword — event series name alone, e.g. 'KubeCon' not 'KubeCon North America 26Q3'"}},
			[]string{"query"}),

		fn("hubspot_search_lists",
			"Search HubSpot contact lists by name keyword. Query broad first (event series name alone) to see "+
				"every edition/country/quarter variant in one call, then pick the match you need — don't iterate "+
				"narrow guesses one at a time.",
			map[string]any{"query": map[string]any{"type": "string", "description": "List name keyword — event series name alone, not a full quarter+country guess"}},
			[]string{"query"}),

		fn("hubspot_get_list",
			"Get details of a HubSpot contact list by ID, including its filter branch.",
			map[string]any{"list_id": map[string]any{"type": "string", "description": "The numeric HubSpot list ID"}},
			[]string{"list_id"}),

		fn("hubspot_create_list",
			"Create a new dynamic HubSpot contact list. "+
				"filter_branch must follow the HubSpot filterBranch schema. "+
				"For custom-event filters (past registrants, education enrolled, etc.) "+
				"use filterBranchType='UNIFIED_EVENTS' with a fixed portal eventTypeId. "+
				"For list-membership filters use filterType='LIST_MEMBERSHIP' or 'IN_LIST'. "+
				"For page-view filters use filterType='PAGE_VIEW'.",
			map[string]any{
				"name":          map[string]any{"type": "string", "description": "List name"},
				"filter_branch": map[string]any{"type": "object", "description": "HubSpot filterBranch object"},
			},
			[]string{"name", "filter_branch"}),

		fn("hubspot_update_list_filters",
			"Replace the filter branch of an existing HubSpot contact list.",
			map[string]any{
				"list_id":       map[string]any{"type": "string"},
				"filter_branch": map[string]any{"type": "object"},
			},
			[]string{"list_id", "filter_branch"}),

		fn("hubspot_get_event_types",
			"List all HubSpot custom event type definitions. Use to find the fullyQualifiedName for behavioral event filters.",
			map[string]any{}, []string{}),

		fn("snowflake_query",
			"Run a SQL query against Snowflake. "+
				"Default database: ANALYTICS, schema: Silver_Segment. "+
				"Use to find past event editions in EVENT_REGISTRATIONS.",
			map[string]any{"sql": map[string]any{"type": "string", "description": "SQL query to execute"}},
			[]string{"sql"}),

		fn("read_reference_file",
			"Read a file from the references/ directory. Use 'brand-master-lists.md' to look up "+
				"brand master list IDs, or 'region-map.md' to look up an event's broader region "+
				"(APAC/EMEA/NA/LATAM) for building the regional-expansion inclusion lists.",
			map[string]any{"filename": map[string]any{"type": "string", "description": "Filename only, e.g. 'brand-master-lists.md' or 'region-map.md'"}},
			[]string{"filename"}),

		fn("present_open_questions",
			"Present open/blocking questions to the user as selectable UI instead of plain text. "+
				"Call this ONCE, during PLANNING only, when something must be confirmed before the "+
				"segment plan can be finalized (location scope, which event(s), job-title approval, "+
				"mailability gate, suppressions to apply, etc). After calling it, stop your turn — "+
				"do not keep building further plan detail past this point; the user's answers will be "+
				"appended to a new planning pass.",
			map[string]any{
				"questions": map[string]any{
					"type":        "array",
					"description": "One entry per open question.",
					"items": map[string]any{
						"type": "object",
						"properties": map[string]any{
							"question":      map[string]any{"type": "string", "description": "The question text"},
							"why_it_blocks": map[string]any{"type": "string", "description": "Why this blocks the build"},
							"options": map[string]any{"type": "array", "items": map[string]any{"type": "string"},
								"description": "Selectable options, e.g. ['Yes', 'No', 'Seoul only', 'Seoul + South Korea']"},
							"allow_custom": map[string]any{"type": "boolean", "description": "Whether a free-text 'Other' answer is allowed (default true)"},
						},
						"required": []string{"question", "options"},
					},
				},
			},
			[]string{"questions"}),
	}
}
