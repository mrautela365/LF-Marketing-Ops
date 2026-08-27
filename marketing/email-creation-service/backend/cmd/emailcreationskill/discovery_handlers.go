package main

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/discovery"
)

// discoveryHandlers wires the 2 LLM-driven Audience Builder discovery
// routes (audience_builder/routes.py's discover_lists / stream_discovery).
// The other 6 audience-builder routes are deterministic and already wired
// in audience_handlers.go from an earlier phase.
type discoveryHandlers struct {
	svc *discovery.Service
}

func (s *Server) mountDiscoveryRoutes(svc *discovery.Service) {
	h := &discoveryHandlers{svc: svc}
	s.router.Post("/api/audience-builder/discover", h.discover)
	s.router.Get("/api/audience-builder/discover-stream/{job_id}", h.discoverStream)
}

// discoverRequest mirrors DiscoverListsRequest.
type discoverRequest struct {
	EventURL string `json:"event_url"`
	QA       string `json:"qa"`
}

func (h *discoveryHandlers) discover(w http.ResponseWriter, r *http.Request) {
	var req discoverRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	eventURL := strings.TrimSpace(req.EventURL)
	if eventURL == "" {
		writeError(w, http.StatusBadRequest, "event_url is required")
		return
	}

	// A background goroutine outlives this request's context, mirroring
	// Python's daemon thread outliving the POST /discover request.
	jobID := h.svc.StartDiscoveryJob(context.Background(), eventURL, req.QA)
	writeJSON(w, http.StatusOK, map[string]any{"job_id": jobID, "event_url": eventURL})
}

func (h *discoveryHandlers) discoverStream(w http.ResponseWriter, r *http.Request) {
	jobID := chi.URLParam(r, "job_id")

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

	for {
		select {
		case <-r.Context().Done():
			return
		case item := <-q:
			writeSSEData(w, item)
			if flusher != nil {
				flusher.Flush()
			}
			if m, ok := item.(map[string]any); ok {
				if done, _ := m["done"].(bool); done {
					h.svc.RemoveJob(jobID)
					return
				}
			}
		case <-time.After(5 * time.Second):
			writeSSEData(w, map[string]any{"type": "heartbeat"})
			if flusher != nil {
				flusher.Flush()
			}
		}
	}
}
