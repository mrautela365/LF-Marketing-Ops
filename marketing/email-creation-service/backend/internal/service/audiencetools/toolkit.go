// Package audiencetools ports audience_tools.py's agentic HubSpot
// audience-list-builder layer: the 10-tool agent loop, its 5 verbatim
// prompts (see prompts_gen.go), and the plan/build job lifecycle. It reuses
// the domain.HubSpotListClient / domain.SnowflakeClient ports already wired
// for earlier phases rather than duplicating HTTP calls, with the single
// deliberate exception of web_fetch (webfetch.go), which Python itself
// implements as a second, independently-cached scraper distinct from the
// wizard's EventPageScraper — this port preserves that duplication.
package audiencetools

import (
	"context"
	"encoding/json"
	"strings"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
)

// Toolkit holds every dependency the 10 audience tools need. It is
// constructed once at server startup and shared by both audiencetools'
// own agent loop and (by composition) the discovery package's read-only
// subset — mirrors discovery_tools.py importing audience_tools directly
// rather than reimplementing any HubSpot/Snowflake/web call.
type Toolkit struct {
	Lists      domain.HubSpotListClient
	Emails     domain.HubSpotEmailClient
	Snowflake  domain.SnowflakeClient
	PortalID   string
	WebFetcher *WebFetcher
}

func NewToolkit(lists domain.HubSpotListClient, emails domain.HubSpotEmailClient, sf domain.SnowflakeClient, portalID string) *Toolkit {
	return &Toolkit{Lists: lists, Emails: emails, Snowflake: sf, PortalID: portalID, WebFetcher: NewWebFetcher()}
}

// WebFetch ports web_fetch(url).
func (tk *Toolkit) WebFetch(url string) map[string]any {
	return tk.WebFetcher.Fetch(url)
}

// HubSpotSearchCampaigns ports hubspot_search_campaigns(query) verbatim:
// GET /marketing/v3/emails?limit=50&sort=-updatedAt (no server-side name
// filter), then a client-side case-insensitive substring match on
// "name subject", truncated to the first 15 matches. Deliberately does NOT
// reuse HubSpotEmailClient.SearchEmails's NameContains (server-side
// name__icontains, no subject match, no stats field) — that call shape
// already consolidates 3 OTHER Python search functions but not this one's
// distinct query/projection; SearchEmails is instead reused here for the
// underlying fetch, called with no NameContains so HubSpot applies no
// server-side filter, replicating Python's un-filtered GET exactly.
func (tk *Toolkit) HubSpotSearchCampaigns(ctx context.Context, query string) map[string]any {
	emails, err := tk.Emails.SearchEmails(ctx, domain.EmailSearchOptions{Limit: 50, OrderBy: "-updatedAt"})
	if err != nil {
		return map[string]any{"error": err.Error()}
	}
	qLower := strings.ToLower(query)
	matches := make([]map[string]any, 0, len(emails))
	for _, e := range emails {
		if strings.Contains(strings.ToLower(e.Name+" "+e.Subject), qLower) {
			stats := e.Stats
			if stats == nil {
				stats = map[string]any{}
			}
			matches = append(matches, map[string]any{
				"id":        e.ID,
				"name":      e.Name,
				"subject":   e.Subject,
				"updatedAt": e.UpdatedAt,
				"stats":     stats,
			})
		}
	}
	if len(matches) > 15 {
		matches = matches[:15]
	}
	return map[string]any{"query": query, "results": matches}
}

// HubSpotSearchLists ports hubspot_search_lists(query).
func (tk *Toolkit) HubSpotSearchLists(ctx context.Context, query string) map[string]any {
	lists, err := tk.Lists.SearchLists(ctx, query, 20)
	if err != nil {
		return map[string]any{"error": err.Error()}
	}
	results := make([]map[string]any, 0, len(lists))
	for _, l := range lists {
		results = append(results, map[string]any{"listId": l.ID, "name": l.Name, "size": l.Size})
	}
	return map[string]any{"query": query, "results": results}
}

// HubSpotGetList ports hubspot_get_list(list_id) — the raw
// GET /crm/v3/lists/{id}?includeFilters=true response shape (id/name/
// filterBranch etc.), not the narrower model.ListInfo projection, since the
// discovery/plan/build prompts inspect fields (processingType, raw
// filterBranch) beyond ListInfo's.
func (tk *Toolkit) HubSpotGetList(ctx context.Context, listID string) map[string]any {
	list, err := tk.Lists.GetList(ctx, listID)
	if err != nil {
		return map[string]any{"error": err.Error()}
	}
	out := map[string]any{
		"listId":         list.ID,
		"name":           list.Name,
		"size":           list.Size,
		"processingType": list.ProcessingType,
	}
	if list.FilterBranch != nil {
		out["filterBranch"] = list.FilterBranch
	}
	return out
}

// toFilterBranch converts the map[string]any the LLM produced (JSON shape
// matching model.FilterBranch's tags) into the typed struct HubSpotListClient
// expects — a marshal/unmarshal round-trip is the simplest faithful bridge
// between the tool schema's "object" type and the Go client's typed input.
func toFilterBranch(raw map[string]any) (model.FilterBranch, error) {
	var fb model.FilterBranch
	b, err := json.Marshal(raw)
	if err != nil {
		return fb, err
	}
	if err := json.Unmarshal(b, &fb); err != nil {
		return fb, err
	}
	return fb, nil
}

// HubSpotCreateList ports hubspot_create_list(name, filter_branch). Filter
// optimization and asset-name tagging both already happen inside
// HubSpotListClient.CreateList (internal/dispatch/hubspot.go), matching
// Python's _optimize_filter_branch + tag_asset_name calls — no duplicate
// call needed here.
func (tk *Toolkit) HubSpotCreateList(ctx context.Context, name string, filterBranch map[string]any) map[string]any {
	fb, err := toFilterBranch(filterBranch)
	if err != nil {
		return map[string]any{"error": err.Error()}
	}
	created, err := tk.Lists.CreateList(ctx, name, fb)
	if err != nil {
		return map[string]any{"error": err.Error()}
	}
	out := map[string]any{"listId": created.ListID, "name": created.Name, "hubspot_url": created.HubSpotURL}
	if created.HasSize {
		out["size"] = created.Size
	} else {
		out["size"] = nil
	}
	return out
}

// HubSpotUpdateListFilters ports hubspot_update_list_filters(list_id,
// filter_branch).
func (tk *Toolkit) HubSpotUpdateListFilters(ctx context.Context, listID string, filterBranch map[string]any) map[string]any {
	fb, err := toFilterBranch(filterBranch)
	if err != nil {
		return map[string]any{"error": err.Error()}
	}
	if err := tk.Lists.UpdateListFilters(ctx, listID, fb); err != nil {
		return map[string]any{"error": err.Error()}
	}
	return map[string]any{
		"listId":      listID,
		"updated":     true,
		"hubspot_url": "https://app.hubspot.com/contacts/" + tk.PortalID + "/objectLists/" + listID + "/filters",
	}
}

// HubSpotGetEventTypes ports hubspot_get_event_types().
func (tk *Toolkit) HubSpotGetEventTypes(ctx context.Context) map[string]any {
	defs, err := tk.Lists.GetEventTypes(ctx)
	if err != nil {
		return map[string]any{"error": err.Error()}
	}
	results := make([]map[string]any, 0, len(defs))
	for _, d := range defs {
		results = append(results, map[string]any{
			"fullyQualifiedName": d.FullyQualifiedName,
			"label":              d.Label,
			"name":               d.Name,
			"properties":         d.Properties,
		})
	}
	return map[string]any{"results": results}
}

// sfJSONSafe mirrors _sf_json_safe — Query already returns JSON-safe Go
// values (string/float64/bool/nil from the driver's row scan), so this is a
// pass-through kept only to name the parity point explicitly.
func sfJSONSafe(v any) any { return v }

// SnowflakeQuery ports snowflake_query(sql).
func (tk *Toolkit) SnowflakeQuery(sql string) map[string]any {
	if tk.Snowflake == nil {
		return map[string]any{"error": "Snowflake not configured"}
	}
	cols, rows, err := tk.Snowflake.Query(sql)
	if err != nil {
		return map[string]any{"error": err.Error()}
	}
	safeRows := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		safe := make(map[string]any, len(r))
		for k, v := range r {
			safe[k] = sfJSONSafe(v)
		}
		safeRows = append(safeRows, safe)
	}
	return map[string]any{"columns": cols, "rows": safeRows, "count": len(safeRows)}
}

// ReadReferenceFile ports read_reference_file(filename).
func (tk *Toolkit) ReadReferenceFile(filename string) map[string]any {
	return readReferenceFile(filename)
}

// PresentOpenQuestions ports present_open_questions(questions) — no side
// effects; the SSE "question" event is emitted by the agent loop's on_event
// handler, which has queue access this function does not.
func (tk *Toolkit) PresentOpenQuestions(questions []any) map[string]any {
	return map[string]any{"presented": len(questions)}
}
