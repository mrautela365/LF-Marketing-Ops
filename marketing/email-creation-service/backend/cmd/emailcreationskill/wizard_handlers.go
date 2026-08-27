package main

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/infrastructure/memory"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/infrastructure/sse"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/stagedetector"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/wizardagent"
)

// wizardHandlers wires the wizard's session-based routes (plan through
// clone/content/chat), porting backend/main.py's core wizard flow. Fields
// are read directly off wizardagent.Agent (Emails/Lists/Scraper are exported)
// rather than duplicated here, so there is exactly one source of truth for
// those dependencies.
type wizardHandlers struct {
	sessions *memory.SessionStore
	broker   *sse.Broker
	agent    *wizardagent.Agent
	modeName string
	portalID string
}

func (s *Server) mountWizardRoutes(sessions *memory.SessionStore, broker *sse.Broker, agent *wizardagent.Agent, modeName, portalID string) *wizardHandlers {
	h := &wizardHandlers{sessions: sessions, broker: broker, agent: agent, modeName: modeName, portalID: portalID}

	s.router.Post("/api/plan", h.plan)
	s.router.Post("/api/plan-start", h.planStart)
	s.router.Get("/api/progress/{token}", h.progress)
	s.router.Post("/api/generate-content", h.generateContent)
	s.router.Post("/api/update-sections", h.updateSections)
	s.router.Post("/api/clone", h.clone)
	s.router.Post("/api/set-send-list", h.setSendList)
	s.router.Post("/api/content", h.content)
	s.router.Post("/api/chat", h.chat)
	s.router.Get("/api/session/{session_id}", h.getSession)
	s.router.Get("/api/lists/search", h.listsSearch)

	return h
}

// --- Plan --------------------------------------------------------------------

func (h *wizardHandlers) decodePlanRequest(r *http.Request) (model.PlanRequest, error) {
	var req model.PlanRequest
	err := json.NewDecoder(r.Body).Decode(&req)
	return req, err
}

// plan is POST /api/plan — the blocking variant of _create_plan_impl.
func (h *wizardHandlers) plan(w http.ResponseWriter, r *http.Request) {
	req, err := h.decodePlanRequest(r)
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	session := h.sessions.Create()
	result, err := h.agent.CreatePlan(r.Context(), session, req, h.modeName, nil)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	h.sessions.Update(session)
	writeJSON(w, http.StatusOK, result)
}

// planStart is POST /api/plan-start — the non-blocking variant: runs
// CreatePlan in a background goroutine, streaming "brief" lines to
// /api/progress/{token}, and returns the token immediately.
func (h *wizardHandlers) planStart(w http.ResponseWriter, r *http.Request) {
	req, err := h.decodePlanRequest(r)
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	token := req.ProgressToken
	if token == "" {
		token = uuid.NewString()
	}
	h.broker.Open(token) // ensure the channel exists before work starts

	// A background goroutine outlives this request's context, exactly as
	// Python's daemon thread outlives the /api/plan-start request — use a
	// fresh background context rather than r.Context() (which is canceled
	// the moment this handler returns).
	go func() {
		ctx := context.Background()
		session := h.sessions.Create()
		emit := func(text string) {
			h.broker.Emit(token, model.ProgressEvent{Type: "brief", Text: text})
		}
		result, err := h.agent.CreatePlan(ctx, session, req, h.modeName, emit)
		if err != nil {
			h.broker.Emit(token, model.ProgressEvent{Type: "error", Text: err.Error()})
			return
		}
		h.sessions.Update(session)
		h.broker.Emit(token, model.ProgressEvent{Type: "plan_done", Result: result})
	}()

	writeJSON(w, http.StatusOK, model.PlanStartResponse{Token: token})
}

// progress is GET /api/progress/{token} — an SSE stream of brief lines,
// porting progress_stream's 5s poll / heartbeat / ~10min idle ceiling.
func (h *wizardHandlers) progress(w http.ResponseWriter, r *http.Request) {
	token := chi.URLParam(r, "token")
	ch := h.broker.Open(token)

	flusher, ok := w.(http.Flusher)
	if !ok {
		writeError(w, http.StatusInternalServerError, "streaming unsupported")
		return
	}

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.WriteHeader(http.StatusOK)

	defer h.broker.Close(token)

	idle := 0
	for {
		select {
		case <-r.Context().Done():
			return
		case item, more := <-ch:
			if !more {
				return
			}
			idle = 0
			writeSSEData(w, item)
			flusher.Flush()
		case <-time.After(5 * time.Second):
			idle++
			if idle > 120 { // ~10 min with no activity → give up
				return
			}
			writeSSEData(w, model.ProgressEvent{Type: "heartbeat"})
			flusher.Flush()
		}
	}
}

func writeSSEData(w http.ResponseWriter, v any) {
	b, err := json.Marshal(v)
	if err != nil {
		return
	}
	w.Write([]byte("data: "))
	w.Write(b)
	w.Write([]byte("\n\n"))
}

// --- Generate content ---------------------------------------------------------

func (h *wizardHandlers) generateContent(w http.ResponseWriter, r *http.Request) {
	var req model.GenerateContentRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	session, ok := h.sessions.Get(req.SessionID)
	if !ok {
		writeError(w, http.StatusNotFound, "Session not found")
		return
	}

	emitBrief := func(text string) {
		if req.ProgressToken != "" {
			h.broker.Emit(req.ProgressToken, model.ProgressEvent{Type: "brief", Text: text})
		}
	}
	emitDone := func(text string) {
		if req.ProgressToken != "" {
			h.broker.Emit(req.ProgressToken, model.ProgressEvent{Type: "brief", Text: text, Done: true})
		}
	}
	emitError := func(text string) {
		if req.ProgressToken != "" {
			h.broker.Emit(req.ProgressToken, model.ProgressEvent{Type: "brief", Text: text, Error: true})
		}
	}

	eventDetails, _ := session.Meta["event_details"].(model.ScrapedEventFull)
	stage := sessionStage(session, eventDetails)
	brandHistory, _ := session.Meta["brand_history"].(map[string]any)

	changeRequest := req.ChangeRequest
	sourceEmailID := stringMeta(session, "content_reference_id")
	referenceIDs, _ := session.Meta["content_reference_ids"].([]string)
	if len(referenceIDs) == 0 && sourceEmailID != "" {
		referenceIDs = []string{sourceEmailID}
	}

	if changeRequest != "" {
		emitBrief("✍️ Revising content: " + truncate(changeRequest, 80))
	} else {
		emitBrief("✍️ Drafting subject, preview text & email body…")
	}

	generated, err := h.agent.GenerateEmailContent(r.Context(), wizardagent.GenerateEmailContentInput{
		EventDetails:  eventDetails,
		Stage:         stageInputFromResult(stage),
		BrandHistory:  brandHistory,
		ChangeRequest: changeRequest,
		SourceEmailID: sourceEmailID,
		ReferenceIDs:  referenceIDs,
	})
	if err != nil {
		emitError("⚠️ Content drafting failed: " + err.Error())
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	session.Meta["generated_subject"] = generated.Subject
	session.Meta["generated_preview"] = generated.PreviewText
	session.Meta["generated_html"] = generated.HTML
	session.Meta["body_html"] = firstNonEmptyStr(generated.BodyHTML, generated.HTML)
	session.Meta["banner_url"] = generated.BannerURL
	session.Meta["sections"] = generated.Sections
	session.Meta["sponsors"] = generated.Sponsors

	emitBrief("🤖 Drafting AI template variant…")
	variantA := h.agent.GenerateAITemplateContent(r.Context(), eventDetails, stage, generated.BannerURL, generated.Sponsors)

	session.Meta["variant_a_subject"] = variantA.Subject
	session.Meta["variant_a_preview"] = variantA.PreviewText
	session.Meta["variant_a_html"] = variantA.HTML
	session.Meta["variant_a_body_html"] = variantA.BodyHTML
	session.Meta["variant_a_sections"] = variantA.Sections
	session.Meta["variant_a_banner_url"] = variantA.BannerURL
	session.Meta["variant_a_template_key"] = variantA.TemplateKey
	session.Meta["variant_a_mode"] = variantA.Mode
	h.sessions.Update(session)

	sections := generated.Sections
	if sections == nil {
		sections = []model.EmailSection{}
	}
	emitDone("📧 Email drafted — " + itoa(len(sections)) + " content section(s).")

	writeJSON(w, http.StatusOK, model.GenerateContentResponse{
		SessionID:           req.SessionID,
		GeneratedSubject:    generated.Subject,
		GeneratedPreview:    generated.PreviewText,
		GeneratedHTML:       generated.HTML,
		Sections:            sections,
		BannerURL:           generated.BannerURL,
		VariantASubject:     variantA.Subject,
		VariantAPreview:     variantA.PreviewText,
		VariantAHTML:        variantA.HTML,
		VariantATemplateKey: variantA.TemplateKey,
		VariantAMode:        variantA.Mode,
	})
}

// --- Update sections -----------------------------------------------------------

func (h *wizardHandlers) updateSections(w http.ResponseWriter, r *http.Request) {
	var req model.UpdateSectionsRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	session, ok := h.sessions.Get(req.SessionID)
	if !ok {
		writeError(w, http.StatusNotFound, "Session not found")
		return
	}

	sections := req.Sections
	if sections == nil {
		sections = []model.EmailSection{}
	}
	eventDetails, _ := session.Meta["event_details"].(model.ScrapedEventFull)
	sponsors, _ := session.Meta["sponsors"].([]model.Sponsor)

	bodyHTML := h.agent.SectionsToHTML(sections, "", sponsors)
	previewHTML := h.agent.BuildEmailPreview(stringMeta(session, "banner_url"), bodyHTML, eventDetails.URL, eventDetails.EventName)

	session.Meta["sections"] = sections
	session.Meta["body_html"] = bodyHTML
	session.Meta["generated_html"] = previewHTML
	h.sessions.Update(session)

	writeJSON(w, http.StatusOK, model.UpdateSectionsResponse{
		SessionID:     req.SessionID,
		GeneratedHTML: previewHTML,
		SectionsCount: len(sections),
	})
}

// --- Clone ---------------------------------------------------------------------

func (h *wizardHandlers) clone(w http.ResponseWriter, r *http.Request) {
	var req model.CloneRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	session, ok := h.sessions.Get(req.SessionID)
	if !ok {
		writeError(w, http.StatusNotFound, "Session not found")
		return
	}
	if session.Phase != "planning" {
		writeError(w, http.StatusBadRequest, "Expected phase 'planning', got '"+session.Phase+"'")
		return
	}
	if !req.Approved {
		writeJSON(w, http.StatusOK, model.CloneResponse{SessionID: req.SessionID, Message: "Plan not approved.", Phase: "planning"})
		return
	}

	text, messages, err := h.agent.CloneTurn(r.Context(), session, wizardagent.CloneTurnInput{
		Subject:     req.Subject,
		PreviewText: req.PreviewText,
		SendListID:  req.SendListID,
	})
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	session.Messages = messages

	// real_email_id: session.EmailID is set by CloneTurn only once a real
	// clone happened during this turn — ports the "Claude may have
	// hallucinated" safety check.
	realEmailID := session.EmailID
	if realEmailID == "" {
		writeError(w, http.StatusInternalServerError,
			"Email was not created in HubSpot — Claude did not call the clone tool. Please try again.")
		return
	}

	contentApplied, _ := session.Meta["content_applied"].(bool)
	validationPassed, _ := session.Meta["validation_passed"].(bool)
	validationIssues, _ := session.Meta["validation_issues"].([]string)

	variantAEmailID := stringMeta(session, "variant_a_email_id")
	if variantAEmailID == "" {
		variantAEmailID = realEmailID
	}
	variantADraftURL := stringMeta(session, "variant_a_draft_url")
	variantBEmailID := stringMeta(session, "variant_b_email_id")
	variantBDraftURL := stringMeta(session, "variant_b_draft_url")

	if validationPassed {
		session.Phase = "complete"
	} else {
		session.Phase = "cloned"
	}
	session.EmailID = realEmailID
	session.DraftURL = "https://app.hubspot.com/email/" + h.portalID + "/edit/" + realEmailID + "/settings"
	h.sessions.Update(session)

	if variantADraftURL == "" {
		variantADraftURL = session.DraftURL
	}

	writeJSON(w, http.StatusOK, model.CloneResponse{
		SessionID:        req.SessionID,
		Message:          text,
		Phase:            session.Phase,
		EmailID:          session.EmailID,
		DraftURL:         session.DraftURL,
		ContentApplied:   contentApplied,
		ValidationPassed: validationPassed,
		ValidationIssues: validationIssues,
		VariantAEmailID:  variantAEmailID,
		VariantADraftURL: variantADraftURL,
		VariantBEmailID:  variantBEmailID,
		VariantBDraftURL: variantBDraftURL,
	})
}

// --- Set send list ---------------------------------------------------------------

func (h *wizardHandlers) setSendList(w http.ResponseWriter, r *http.Request) {
	var req model.SetSendListRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	sendListIDs := trimNonEmpty(req.SendListIDs)
	if len(sendListIDs) == 0 && strings.TrimSpace(req.SendListID) != "" {
		sendListIDs = []string{strings.TrimSpace(req.SendListID)}
	}
	if len(sendListIDs) == 0 {
		writeError(w, http.StatusBadRequest, "send_list_id or send_list_ids is required")
		return
	}

	emailID := strings.TrimSpace(req.EmailID)
	suppression := req.SuppressionListIDs

	var sess *model.SessionState
	if req.SessionID != "" {
		if s, ok := h.sessions.Get(req.SessionID); ok {
			sess = s
			if emailID == "" {
				emailID = sess.EmailID
			}
			if len(suppression) == 0 {
				if brand, ok := sess.Meta["brand_history"].(map[string]any); ok {
					if v, ok := brand["suppression_list_ids"].([]string); ok {
						suppression = v
					}
				}
			}
		}
	}

	if emailID == "" {
		writeError(w, http.StatusBadRequest, "No email to update. Provide email_id, or a session_id whose email has been cloned.")
		return
	}

	result, err := h.agent.SetEmailSendList(r.Context(), emailID, sendListIDs, suppression)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "Failed to apply send list: "+err.Error())
		return
	}

	if sess != nil {
		if len(sendListIDs) == 1 {
			sess.Meta["audience_list_id"] = sendListIDs[0]
		} else {
			sess.Meta["audience_list_id"] = sendListIDs
		}
		h.sessions.Update(sess)
	}

	sendListIDDisplay := sendListIDs[0]
	if len(sendListIDs) > 1 {
		sendListIDDisplay = strings.Join(sendListIDs, ", ")
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"email_id":     emailID,
		"send_list_id": sendListIDDisplay,
		"list_type":    result.ListType,
		"success":      result.Success,
		"to":           result.To,
	})
}

// --- Content ---------------------------------------------------------------------

func (h *wizardHandlers) content(w http.ResponseWriter, r *http.Request) {
	var req struct {
		SessionID string `json:"session_id"`
		Content   string `json:"content"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	session, ok := h.sessions.Get(req.SessionID)
	if !ok {
		writeError(w, http.StatusNotFound, "Session not found")
		return
	}
	if session.Phase != "cloned" && session.Phase != "complete" {
		writeError(w, http.StatusBadRequest, "Expected phase 'cloned' or 'complete', got '"+session.Phase+"'")
		return
	}

	text, messages, err := h.agent.ContentTurn(r.Context(), session, req.Content)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	session.Messages = messages
	session.Phase = "complete"
	h.sessions.Update(session)

	writeJSON(w, http.StatusOK, map[string]any{
		"session_id": req.SessionID,
		"message":    text,
		"phase":      session.Phase,
		"draft_url":  session.DraftURL,
	})
}

// --- Chat --------------------------------------------------------------------

func (h *wizardHandlers) chat(w http.ResponseWriter, r *http.Request) {
	var req model.ChatRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	session, ok := h.sessions.Get(req.SessionID)
	if !ok {
		writeError(w, http.StatusNotFound, "Session not found")
		return
	}

	text, messages, err := h.agent.ChatTurn(r.Context(), session, req.Message)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	session.Messages = messages
	h.sessions.Update(session)

	writeJSON(w, http.StatusOK, model.ChatResponse{
		SessionID: req.SessionID,
		Message:   text,
		Phase:     session.Phase,
		DraftURL:  session.DraftURL,
	})
}

// --- Session / lists search -----------------------------------------------------

func (h *wizardHandlers) getSession(w http.ResponseWriter, r *http.Request) {
	sessionID := chi.URLParam(r, "session_id")
	session, ok := h.sessions.Get(sessionID)
	if !ok {
		writeError(w, http.StatusNotFound, "Session not found")
		return
	}
	writeJSON(w, http.StatusOK, model.SessionSummary{
		SessionID: sessionID,
		Phase:     session.Phase,
		Plan:      session.Plan,
		EmailID:   session.EmailID,
		DraftURL:  session.DraftURL,
	})
}

func (h *wizardHandlers) listsSearch(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query().Get("q")
	if len(q) < 2 {
		writeJSON(w, http.StatusOK, map[string]any{"lists": []model.ListInfo{}})
		return
	}
	results, err := h.agent.Lists.SearchListsByName(r.Context(), q, 10)
	if err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"lists": results})
}

// --- shared helpers ------------------------------------------------------------

func sessionStage(session *model.SessionState, eventDetails model.ScrapedEventFull) stagedetector.Result {
	if r, ok := session.Meta["stage_result"].(stagedetector.Result); ok {
		return r
	}
	return stagedetector.DetectStage(eventDetails.EventDates)
}

func stageInputFromResult(r stagedetector.Result) wizardagent.StageInput {
	return wizardagent.StageInput{
		Name:              r.Name,
		Funnel:            r.Funnel,
		CTALabel:          r.CTALabel,
		EventDateStr:      r.EventDateStr,
		DaysToEvent:       r.DaysToEvent,
		MarketingStrategy: r.MarketingStrategy,
		ContentIdeas:      r.ContentIdeas,
		StageNumber:       r.StageNumber,
	}
}

func stringMeta(session *model.SessionState, key string) string {
	if v, ok := session.Meta[key].(string); ok {
		return v
	}
	return ""
}

func firstNonEmptyStr(vals ...string) string {
	for _, v := range vals {
		if v != "" {
			return v
		}
	}
	return ""
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}

func itoa(n int) string {
	return strings.TrimSpace(json.Number(itoaRaw(n)).String())
}

func itoaRaw(n int) string {
	if n == 0 {
		return "0"
	}
	neg := n < 0
	if neg {
		n = -n
	}
	var b []byte
	for n > 0 {
		b = append([]byte{byte('0' + n%10)}, b...)
		n /= 10
	}
	if neg {
		b = append([]byte{'-'}, b...)
	}
	return string(b)
}

func trimNonEmpty(vals []string) []string {
	var out []string
	for _, v := range vals {
		v = strings.TrimSpace(v)
		if v != "" {
			out = append(out, v)
		}
	}
	return out
}
