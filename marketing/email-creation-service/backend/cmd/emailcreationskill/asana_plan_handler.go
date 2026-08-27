package main

import (
	"encoding/json"
	"net/http"
	"sync"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/eventbrands"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/wizardagent"
)

// asanaPlanHandlers implements POST /api/plan-from-asana, porting main.py's
// plan_from_asana route: fetch an Asana task's brief (via REST when
// ASANA_ACCESS_TOKEN is configured, else via the agent's MCP fallback),
// then best-effort enrich it with a HubSpot brand/source-email match and
// the linked Google Doc's HTML.
type asanaPlanHandlers struct {
	agent       *wizardagent.Agent
	asanaClient domain.AsanaClient // nil when ASANA_ACCESS_TOKEN isn't configured
}

func (s *Server) mountAsanaPlanRoutes(agent *wizardagent.Agent, asanaClient domain.AsanaClient) {
	h := &asanaPlanHandlers{agent: agent, asanaClient: asanaClient}
	s.router.Post("/api/plan-from-asana", h.handle)
}

func (h *asanaPlanHandlers) handle(w http.ResponseWriter, r *http.Request) {
	var req model.AsanaPlanRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	var warnings []string
	var brief model.EmailBrief

	// --- Step 1: fetch the Asana task's brief. ---
	if h.asanaClient != nil {
		gid, err := h.asanaClient.ParseTaskGID(req.AsanaURL)
		if err != nil {
			writeError(w, http.StatusBadRequest, err.Error())
			return
		}
		task, err := h.asanaClient.GetTask(gid)
		if err != nil {
			writeError(w, http.StatusInternalServerError, err.Error())
			return
		}
		subtasks, err := h.asanaClient.GetSubtasks(gid)
		if err != nil {
			writeError(w, http.StatusInternalServerError, err.Error())
			return
		}

		// Concurrent story fetch across [task gid] + every subtask gid,
		// replacing Python's asyncio.gather.
		gids := make([]string, 0, 1+len(subtasks))
		gids = append(gids, gid)
		for _, st := range subtasks {
			gids = append(gids, st.GID)
		}
		allStories := make(map[string][]model.AsanaStory, len(gids))
		var mu sync.Mutex
		var wg sync.WaitGroup
		for _, g := range gids {
			g := g
			wg.Add(1)
			go func() {
				defer wg.Done()
				stories, err := h.asanaClient.GetStories(g)
				if err != nil {
					return
				}
				mu.Lock()
				allStories[g] = stories
				mu.Unlock()
			}()
		}
		wg.Wait()

		brief = h.asanaClient.ExtractBrief(task, subtasks, allStories)
	} else {
		// MCP fallback — ASANA_ACCESS_TOKEN not configured.
		fetched, ok, err := h.agent.FetchAsanaTaskViaMCP(r.Context(), req.AsanaURL)
		if err != nil || !ok {
			msg := "ASANA_ACCESS_TOKEN is not configured and MCP fallback failed"
			if err != nil {
				msg += ": " + err.Error()
			}
			msg += ". Add ASANA_ACCESS_TOKEN to your .env file, or authenticate the Asana MCP connector."
			writeError(w, http.StatusServiceUnavailable, msg)
			return
		}
		brief = model.EmailBrief{
			EmailName:    fetched.EmailName,
			SubtaskNames: fetched.SubtaskNames,
		}
		if fetched.Raw != nil {
			if v, ok := fetched.Raw["brand_name"].(string); ok {
				brief.BrandName = v
			}
			if v, ok := fetched.Raw["task_name"].(string); ok {
				brief.TaskName = v
			}
			if v, ok := fetched.Raw["content_doc_url"].(string); ok {
				brief.ContentDocURL = v
			}
			if v, ok := fetched.Raw["audience_instructions"].(string); ok {
				brief.AudienceInstructions = v
			}
			if v, ok := fetched.Raw["event_url"].(string); ok {
				brief.EventURL = v
			}
			if v, ok := fetched.Raw["due_on"].(string); ok {
				brief.DueOn = v
			}
		}
		warnings = append(warnings, "ASANA_ACCESS_TOKEN not configured — task data fetched via MCP connector (may be slower).")
	}

	result := model.AsanaPlanResult{
		EmailName:            brief.EmailName,
		SuppressionListIDs:   []string{},
		AudienceInstructions: brief.AudienceInstructions,
		EventURL:             brief.EventURL,
		TaskName:             brief.TaskName,
		DueOn:                brief.DueOn,
		SubtaskNames:         brief.SubtaskNames,
	}

	// --- Step 2: best-effort HubSpot brand/source-email lookup. ---
	func() {
		defer func() {
			if rec := recover(); rec != nil {
				warnings = append(warnings, "HubSpot brand search failed (internal error).")
			}
		}()

		eventName := ""
		location := ""
		brandNameGuess := brief.BrandName

		if brief.EventURL != "" {
			scraped := h.agent.Scraper.ScrapeEventFull(brief.EventURL)
			eventName = scraped.EventName
			location = scraped.Location
			if brandNameGuess == "" {
				brandNameGuess = scraped.BrandName
			}
			result.EventURL = brief.EventURL
		}

		if brandNameGuess == "" && eventName == "" {
			warnings = append(warnings, "Could not determine brand name from task — no HubSpot search performed.")
			return
		}

		known, _ := eventbrands.LookupEventBrand(firstNonEmptyStr(eventName, brandNameGuess))
		shortBrandName := known.ShortBrandName
		brandName := firstNonEmptyStr(known.BrandName, brandNameGuess)

		var eventShortNames []string
		if shortBrandName != "" {
			seen := map[string]bool{}
			for _, e := range eventbrands.GetBrandEvents(shortBrandName) {
				if !seen[e.EventShortName] {
					seen[e.EventShortName] = true
					eventShortNames = append(eventShortNames, e.EventShortName)
				}
			}
		}

		candidates, err := h.agent.Emails.GetBrandEmails(r.Context(), domain.GetBrandEmailsOptions{
			ShortBrandName:  shortBrandName,
			BrandName:       brandName,
			EventShortNames: eventShortNames,
			EventURL:        brief.EventURL,
		})
		if err != nil || len(candidates) == 0 {
			warnings = append(warnings, "No sent emails found for this brand/event in HubSpot.")
			return
		}

		pool, _ := eventbrands.FilterCandidatesByLocale(candidates, firstNonEmptyStr(eventName, brandName), location, func(e model.EmailSummary) string { return e.Name })

		cands := make([]wizardagent.SourceEmailCandidate, len(pool))
		for i, e := range pool {
			cands[i] = wizardagent.SourceEmailCandidate{EmailID: e.ID, Name: e.Name, PublishDate: e.PublishDate}
		}
		selectedID, ok := h.agent.AISelectSourceEmail(r.Context(), firstNonEmptyStr(eventName, brandName), known.EventShortName, location, cands, brief.EventURL, 5)
		if !ok {
			warnings = append(warnings, "Could not confidently select a matching source email — please choose one manually.")
			return
		}

		var selected *model.EmailSummary
		for i := range pool {
			if pool[i].ID == selectedID {
				selected = &pool[i]
				break
			}
		}
		if selected == nil {
			warnings = append(warnings, "Could not confidently select a matching source email — please choose one manually.")
			return
		}

		result.FromName = selected.From.FromName
		result.FromAddress = selected.From.ReplyTo
		result.EmailType = firstNonEmptyStr(selected.Type, "BATCH_EMAIL")
		result.CloneBaseID = selected.ID
		result.CloneBaseName = selected.Name
		result.SuppressionListIDs = unionStr(selected.To.ContactIlsLists.Exclude, selected.To.ContactLists.Exclude)
		included := unionStr(selected.To.ContactIlsLists.Include, selected.To.ContactLists.Include)
		if len(included) > 0 {
			result.SendListID = included[0]
		}
	}()

	// --- Step 3: fetch the linked Google Doc's HTML. ---
	if brief.ContentDocURL != "" {
		html, err := h.agent.Scraper.PrepareContent(brief.ContentDocURL)
		if err != nil {
			warnings = append(warnings, "Failed to fetch content doc: "+err.Error())
		} else {
			result.DocHTML = html
			result.DocURL = brief.ContentDocURL
		}
	}

	result.Warnings = warnings
	writeJSON(w, http.StatusOK, result)
}

func unionStr(a, b []string) []string {
	seen := map[string]bool{}
	var out []string
	for _, v := range a {
		if v != "" && !seen[v] {
			seen[v] = true
			out = append(out, v)
		}
	}
	for _, v := range b {
		if v != "" && !seen[v] {
			seen[v] = true
			out = append(out, v)
		}
	}
	return out
}
