package main

import (
	"encoding/json"
	"errors"
	"net/http"
	"strconv"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/audience"
)

// audienceHandlers wires the 8 deterministic /api/audience-builder/* routes
// (ported from audience_builder/routes.py). The 2 LLM-driven routes
// (/discover, /discover-stream/{job_id}) are deferred to migration phase 5.
type audienceHandlers struct {
	lists       domain.HubSpotListClient
	masterLists *audience.MasterListService
	lastSent    *audience.LastSentService
	qa          *audience.QaService
}

func (s *Server) mountAudienceBuilderRoutes(lists domain.HubSpotListClient, emails domain.HubSpotEmailClient, portalID string) {
	h := &audienceHandlers{
		lists:       lists,
		masterLists: audience.NewMasterListService(lists, portalID),
		lastSent:    audience.NewLastSentService(emails, lists, portalID),
		qa:          audience.NewQaService(lists, portalID),
	}

	s.router.Get("/api/audience-builder/lists/search", h.searchLists)
	s.router.Get("/api/audience-builder/suppression-lists", h.suppressionLists)
	s.router.Get("/api/audience-builder/last-sent", h.lastSentEmails)
	s.router.Get("/api/audience-builder/existing-master-lists", h.existingMasterLists)
	s.router.Post("/api/audience-builder/preview-count", h.previewCount)
	s.router.Post("/api/audience-builder/compose-master", h.composeMaster)
	s.router.Post("/api/audience-builder/qa/run", h.qaRun)
	s.router.Get("/api/audience-builder/qa/report.xlsx", h.qaReport)
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, detail string) {
	writeJSON(w, status, map[string]string{"detail": detail})
}

func (h *audienceHandlers) searchLists(w http.ResponseWriter, r *http.Request) {
	query := r.URL.Query().Get("q")
	if query == "" {
		writeJSON(w, http.StatusOK, map[string]any{"query": "", "results": []model.ListInfo{}})
		return
	}
	results, err := h.lists.SearchLists(r.Context(), query, 20)
	if err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"query": query, "results": results})
}

func (h *audienceHandlers) suppressionLists(w http.ResponseWriter, r *http.Request) {
	brandShort := r.URL.Query().Get("brand_short")
	eventName := r.URL.Query().Get("event_name")
	results := h.masterLists.FindStandardSuppressionLists(r.Context(), brandShort, eventName)
	writeJSON(w, http.StatusOK, map[string]any{"results": results})
}

func (h *audienceHandlers) lastSentEmails(w http.ResponseWriter, r *http.Request) {
	eventName := r.URL.Query().Get("event_name")
	brandShort := r.URL.Query().Get("brand_short")
	results, err := h.lastSent.FindLastSentEmails(r.Context(), eventName, brandShort, 3)
	if err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"results": results})
}

func (h *audienceHandlers) existingMasterLists(w http.ResponseWriter, r *http.Request) {
	eventName := r.URL.Query().Get("event_name")
	brandShort := r.URL.Query().Get("brand_short")
	results := h.masterLists.FindExistingMasterLists(r.Context(), brandShort, eventName)
	writeJSON(w, http.StatusOK, map[string]any{"results": results})
}

func (h *audienceHandlers) previewCount(w http.ResponseWriter, r *http.Request) {
	var req model.PreviewCountRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if len(req.ListIDs) == 0 {
		writeError(w, http.StatusBadRequest, "list_ids must not be empty")
		return
	}
	result := h.masterLists.UnionSize(r.Context(), req.ListIDs, 0)
	writeJSON(w, http.StatusOK, result)
}

func (h *audienceHandlers) composeMaster(w http.ResponseWriter, r *http.Request) {
	var req model.ComposeMasterListRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if len(req.ListIDs) == 0 {
		writeError(w, http.StatusBadRequest, "list_ids must not be empty")
		return
	}
	result, err := h.masterLists.ComposeMasterListFromIDs(
		r.Context(), req.ListIDs, req.Name, req.EventURL, req.BrandShort, req.EventName, nil, req.ExcludeListIDs,
	)
	if err != nil {
		if errors.Is(err, domain.ErrInvalidInput) {
			writeError(w, http.StatusBadRequest, err.Error())
			return
		}
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, result)
}

func (h *audienceHandlers) qaRun(w http.ResponseWriter, r *http.Request) {
	var req model.QaRunRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	resolved, err := h.qa.ResolveListRef(r.Context(), req.ListRef)
	if err != nil {
		if errors.Is(err, domain.ErrInvalidInput) {
			writeError(w, http.StatusBadRequest, err.Error())
			return
		}
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	if len(resolved.Candidates) > 0 {
		writeJSON(w, http.StatusOK, map[string]any{"needs_disambiguation": true, "candidates": resolved.Candidates})
		return
	}

	result, err := h.qa.RunQaOnList(r.Context(), resolved.ListID, req.TargetsEU, req.TargetsCA)
	if err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"needs_disambiguation": false,
		"list_id":              result.ListID,
		"name":                 result.Name,
		"hubspot_url":          result.HubSpotURL,
		"checks":               result.Checks,
		"findings":             result.Findings,
		"overall":              result.Overall,
	})
}

func (h *audienceHandlers) qaReport(w http.ResponseWriter, r *http.Request) {
	listID := r.URL.Query().Get("list_id")
	targetsEU, _ := strconv.ParseBool(r.URL.Query().Get("targets_eu"))
	targetsCA, _ := strconv.ParseBool(r.URL.Query().Get("targets_ca"))

	result, err := h.qa.RunQaOnList(r.Context(), listID, targetsEU, targetsCA)
	if err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	xlsxBytes, err := audience.BuildQaWorkbook(result)
	if err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}

	w.Header().Set("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
	w.Header().Set("Content-Disposition", `attachment; filename="audience-qa-`+listID+`.xlsx"`)
	w.Write(xlsxBytes)
}
