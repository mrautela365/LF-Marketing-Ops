package main

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/infrastructure/config"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/infrastructure/memory"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/audiencetools"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/wizardagent"
)

// audienceJobHandlers wires the 8 audience-list-builder job routes ported
// from main.py's "Audience list builder" section (start_audience_plan
// through stream_audience_build). These are distinct from the 8
// audience_handlers.go routes (deterministic master-list-composer helpers)
// and the 2 discovery_handlers.go routes (existing-list discovery).
type audienceJobHandlers struct {
	sessions *memory.SessionStore
	svc      *audiencetools.Service
	agent    *wizardagent.Agent
	cfg      *config.Config
	portalID string
}

func (s *Server) mountAudienceJobRoutes(sessions *memory.SessionStore, svc *audiencetools.Service, agent *wizardagent.Agent, cfg *config.Config, portalID string) {
	h := &audienceJobHandlers{sessions: sessions, svc: svc, agent: agent, cfg: cfg, portalID: portalID}

	s.router.Post("/api/audience-plan", h.startAudiencePlan)
	s.router.Post("/api/build-audience", h.startBuildAudience)
	s.router.Post("/api/audience/plan", h.startAudiencePlanStandalone)
	s.router.Post("/api/audience/run", h.runAudienceStandalone)
	s.router.Post("/api/audience/custom-plan", h.startCustomAudiencePlan)
	s.router.Post("/api/audience/custom-run", h.runCustomAudience)
	s.router.Get("/api/audience/status", h.audienceStatus)
	s.router.Get("/api/audience-stream/{job_id}", h.streamAudienceBuild)
}

// --- request shapes (ports backend/models.py's 5 audience request models) ---

type audiencePlanRequest struct {
	SessionID string `json:"session_id"`
	EventURL  string `json:"event_url"`
	QA        string `json:"qa"`
}

type audienceRunRequest struct {
	EventURL  string `json:"event_url"`
	SessionID string `json:"session_id"`
	Plan      string `json:"plan"`
	QA        string `json:"qa"`
}

type buildAudienceRequest struct {
	SessionID string `json:"session_id"`
	EventURL  string `json:"event_url"`
	Plan      string `json:"plan"`
	QA        string `json:"qa"`
}

type customAudiencePlanRequest struct {
	Request   string `json:"request"`
	SessionID string `json:"session_id"`
	QA        string `json:"qa"`
}

type customAudienceRunRequest struct {
	Request   string `json:"request"`
	SessionID string `json:"session_id"`
	Plan      string `json:"plan"`
	QA        string `json:"qa"`
}

// prescrapedFromSession ports the `cached = session.meta.get("url_data") or {}`
// / `prescraped = cached if cached.get("url") == event_url else None` idiom
// shared by start_audience_plan and start_build_audience: reuse the scrape
// already done during the Email Content stage only if it was for this same
// URL.
func prescrapedFromSession(sess *model.SessionState, eventURL string) (*audiencetools.Prescraped, string) {
	cachedURL := ""
	raw, ok := sess.Meta["url_data"]
	if !ok {
		return nil, ""
	}
	scraped, ok := raw.(model.ScrapedEventFull)
	if !ok {
		return nil, ""
	}
	cachedURL = scraped.URL
	if eventURL == "" {
		eventURL = cachedURL
	}
	if cachedURL != eventURL || cachedURL == "" {
		return nil, eventURL
	}
	return &audiencetools.Prescraped{
		EventDates:  scraped.EventDates,
		Headings:    scraped.Headings,
		EventName:   scraped.EventName,
		BrandName:   scraped.BrandName,
		Location:    scraped.Location,
		Description: scraped.Description,
	}, eventURL
}

// startAudiencePlan is POST /api/audience-plan.
func (h *audienceJobHandlers) startAudiencePlan(w http.ResponseWriter, r *http.Request) {
	var req audiencePlanRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	sess, ok := h.sessions.Get(req.SessionID)
	if !ok {
		writeError(w, http.StatusNotFound, "Session not found")
		return
	}

	eventURL := strings.TrimSpace(req.EventURL)
	prescraped, resolvedURL := prescrapedFromSession(sess, eventURL)
	if eventURL == "" {
		eventURL = resolvedURL
	}
	if eventURL == "" {
		writeError(w, http.StatusBadRequest, "No event URL — provide event_url or run plan first")
		return
	}

	jobID := h.svc.StartPlanJob(context.Background(), eventURL, prescraped, req.QA)
	writeJSON(w, http.StatusOK, map[string]any{"job_id": jobID, "event_url": eventURL})
}

// startBuildAudience is POST /api/build-audience.
func (h *audienceJobHandlers) startBuildAudience(w http.ResponseWriter, r *http.Request) {
	var req buildAudienceRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	sess, ok := h.sessions.Get(req.SessionID)
	if !ok {
		writeError(w, http.StatusNotFound, "Session not found")
		return
	}

	eventURL := strings.TrimSpace(req.EventURL)
	prescraped, resolvedURL := prescrapedFromSession(sess, eventURL)
	if eventURL == "" {
		eventURL = resolvedURL
	}
	if eventURL == "" {
		writeError(w, http.StatusBadRequest, "No event URL — provide event_url or run plan first")
		return
	}

	jobID := h.svc.StartBuildJob(context.Background(), eventURL, req.Plan, req.QA, prescraped)
	writeJSON(w, http.StatusOK, map[string]any{"job_id": jobID, "event_url": eventURL})
}

// startAudiencePlanStandalone is POST /api/audience/plan.
func (h *audienceJobHandlers) startAudiencePlanStandalone(w http.ResponseWriter, r *http.Request) {
	var req audienceRunRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	eventURL := strings.TrimSpace(req.EventURL)
	if eventURL == "" {
		writeError(w, http.StatusBadRequest, "event_url is required")
		return
	}
	jobID := h.svc.StartPlanJob(context.Background(), eventURL, nil, req.QA)
	writeJSON(w, http.StatusOK, map[string]any{"job_id": jobID, "event_url": eventURL})
}

// runAudienceStandalone is POST /api/audience/run.
func (h *audienceJobHandlers) runAudienceStandalone(w http.ResponseWriter, r *http.Request) {
	var req audienceRunRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	eventURL := strings.TrimSpace(req.EventURL)
	if eventURL == "" {
		writeError(w, http.StatusBadRequest, "event_url is required")
		return
	}
	jobID := h.svc.StartBuildJob(context.Background(), eventURL, req.Plan, req.QA, nil)
	writeJSON(w, http.StatusOK, map[string]any{"job_id": jobID, "event_url": eventURL})
}

// startCustomAudiencePlan is POST /api/audience/custom-plan.
func (h *audienceJobHandlers) startCustomAudiencePlan(w http.ResponseWriter, r *http.Request) {
	var req customAudiencePlanRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	requestText := strings.TrimSpace(req.Request)
	if requestText == "" {
		writeError(w, http.StatusBadRequest, "request is required")
		return
	}
	jobID := h.svc.StartCustomPlanJob(context.Background(), requestText, req.QA)
	writeJSON(w, http.StatusOK, map[string]any{"job_id": jobID})
}

// runCustomAudience is POST /api/audience/custom-run.
func (h *audienceJobHandlers) runCustomAudience(w http.ResponseWriter, r *http.Request) {
	var req customAudienceRunRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	requestText := strings.TrimSpace(req.Request)
	if requestText == "" {
		writeError(w, http.StatusBadRequest, "request is required")
		return
	}
	jobID := h.svc.StartCustomBuildJob(context.Background(), requestText, req.Plan, req.QA)
	writeJSON(w, http.StatusOK, map[string]any{"job_id": jobID})
}

// audienceStatus is GET /api/audience/status.
func (h *audienceJobHandlers) audienceStatus(w http.ResponseWriter, r *http.Request) {
	hasLiteLLM := h.cfg.LiteLLMBaseURL != "" && h.cfg.LiteLLMAPIKey != ""
	mode := "cli"
	if hasLiteLLM {
		mode = "litellm"
	}
	var litellmBaseURL any
	if h.cfg.LiteLLMBaseURL != "" {
		litellmBaseURL = h.cfg.LiteLLMBaseURL
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"mode":              mode,
		"litellm_base_url":  litellmBaseURL,
		"litellm_key_set":   h.cfg.LiteLLMAPIKey != "",
		"hubspot_token_set": h.cfg.HubSpotAccessToken != "",
	})
}

// streamAudienceBuild is GET /api/audience-stream/{job_id}?session_id=.
// Ports stream_audience_build's full completion-handling logic verbatim:
// prefers the master_list_id captured straight from tool-result tracking
// over a text-extraction fallback, stores it (plus any suppression lists
// parsed from the accumulated output) in the session, and — if the
// session's email was already cloned — applies the send list post-hoc via
// the same SetEmailSendList path the wizard's own /api/set-send-list uses.
func (h *audienceJobHandlers) streamAudienceBuild(w http.ResponseWriter, r *http.Request) {
	jobID := chi.URLParam(r, "job_id")
	sessionID := r.URL.Query().Get("session_id")

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("X-Accel-Buffering", "no")
	w.WriteHeader(http.StatusOK)
	flusher, _ := w.(http.Flusher)

	q, ok := h.svc.GetJobQueue(jobID)
	if !ok {
		writeSSEData(w, map[string]any{"type": "error", "text": "Job not found", "done": true})
		if flusher != nil {
			flusher.Flush()
		}
		return
	}

	var accumulated []string
	for {
		select {
		case <-r.Context().Done():
			return
		case <-time.After(5 * time.Second):
			writeSSEData(w, map[string]any{"type": "heartbeat"})
			if flusher != nil {
				flusher.Flush()
			}
			continue
		case item := <-q:
			m, _ := item.(map[string]any)
			if m == nil {
				continue
			}
			if m["type"] == "output" {
				if text, _ := m["text"].(string); text != "" {
					accumulated = append(accumulated, text)
				}
			}
			writeSSEData(w, m)
			if flusher != nil {
				flusher.Flush()
			}

			done, _ := m["done"].(bool)
			if !done {
				continue
			}

			h.handleBuildComplete(r.Context(), w, flusher, jobID, sessionID, accumulated, m)
			return
		}
	}
}

func (h *audienceJobHandlers) handleBuildComplete(ctx context.Context, w http.ResponseWriter, flusher http.Flusher, jobID, sessionID string, accumulated []string, item map[string]any) {
	defer h.svc.RemoveJob(jobID)

	allText := strings.Join(accumulated, "\n")

	masterID := strings.TrimSpace(strOfAny(item["master_list_id"]))
	if masterID == "" {
		if extracted := audiencetools.ExtractMasterListID(allText); extracted != "" {
			masterID = extracted
		}
	}
	suppressionLists := audiencetools.ExtractSuppressionLists(allText)
	posthocApplied := false

	if sessionID != "" && masterID != "" {
		if sess, ok := h.sessions.Get(sessionID); ok {
			sess.Meta["audience_list_id"] = masterID
			if len(suppressionLists) > 0 {
				sess.Meta["suppression_lists"] = suppressionLists
			}
			h.sessions.Update(sess)

			if sess.EmailID != "" {
				var historyIDs []string
				if brand, ok := sess.Meta["brand_history"].(map[string]any); ok {
					if v, ok := brand["suppression_list_ids"].([]string); ok {
						historyIDs = v
					}
				}
				freshIDs := make([]string, 0, len(suppressionLists))
				for _, row := range suppressionLists {
					if row.ListID != "" {
						freshIDs = append(freshIDs, row.ListID)
					}
				}
				suppressionIDs := dedupStrings(append(append([]string{}, historyIDs...), freshIDs...))
				if res, err := h.agent.SetEmailSendList(ctx, sess.EmailID, []string{masterID}, suppressionIDs); err == nil {
					posthocApplied = res.Success
				}
			}
		}
	}

	masterListURL := ""
	if masterID != "" {
		masterListURL = "https://app.hubspot.com/contacts/" + h.portalID + "/objectLists/" + masterID + "/filters"
	}
	success, _ := item["success"].(bool)
	writeSSEData(w, map[string]any{
		"type": "complete", "done": true,
		"master_list_id":    masterID,
		"master_list_url":   masterListURL,
		"suppression_lists": suppressionLists,
		"posthoc_applied":   posthocApplied,
		"success":           success,
	})
	if flusher != nil {
		flusher.Flush()
	}
}

func strOfAny(v any) string {
	s, _ := v.(string)
	return s
}

func dedupStrings(in []string) []string {
	seen := map[string]bool{}
	out := make([]string, 0, len(in))
	for _, s := range in {
		if s == "" || seen[s] {
			continue
		}
		seen[s] = true
		out = append(out, s)
	}
	return out
}
