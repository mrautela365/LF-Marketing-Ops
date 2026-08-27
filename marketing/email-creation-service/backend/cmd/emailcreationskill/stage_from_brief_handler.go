package main

import (
	"encoding/json"
	"net/http"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/stagedetector"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/wizardagent"
)

// stageFromBriefHandlers implements POST /api/stage-from-brief, the
// stateless clone+settings+content call used by the email-staging skill.
// It bypasses sessions entirely, porting main.py's stage_from_brief route.
type stageFromBriefHandlers struct {
	agent            *wizardagent.Agent
	portalID         string
	internalAPIToken string
}

func (s *Server) mountStageFromBriefRoutes(agent *wizardagent.Agent, portalID, internalAPIToken string) {
	h := &stageFromBriefHandlers{agent: agent, portalID: portalID, internalAPIToken: internalAPIToken}
	s.router.Post("/api/stage-from-brief", h.handle)
}

func (h *stageFromBriefHandlers) handle(w http.ResponseWriter, r *http.Request) {
	// Auth gate: 401 if INTERNAL_API_TOKEN is configured and the caller's
	// token doesn't match; if unconfigured, allow through unauthenticated
	// (matches Python's local-dev-only relaxation, not a new one).
	var req model.StagingBriefRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	if h.internalAPIToken != "" && req.InternalToken != h.internalAPIToken {
		writeError(w, http.StatusUnauthorized, "Invalid or missing internal_token")
		return
	}

	// Step 1: clone.
	cloned, err := h.agent.Emails.CloneEmail(r.Context(), req.CloneBaseID, req.EmailName)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "Clone failed: "+err.Error())
		return
	}
	emailID := cloned.EmailID
	draftURL := cloned.DraftURL
	if draftURL == "" {
		draftURL = "https://app.hubspot.com/email/" + h.portalID + "/edit/" + emailID + "/settings"
	}

	// Step 2: settings + send list — Python bundles both concerns into one
	// update_email_settings(**kwargs) call; Go's domain ports split them,
	// so this issues two calls to reproduce the same net effect.
	settings := domain.EmailSettingsUpdate{}
	if req.FromName != "" {
		settings.FromName = &req.FromName
	}
	if req.FromAddress != "" {
		settings.ReplyTo = &req.FromAddress
	}
	if req.Subject != "" {
		settings.Subject = &req.Subject
	}
	if req.PreviewText != "" {
		settings.PreviewText = &req.PreviewText
	}
	if req.EmailType != "" {
		settings.Type = &req.EmailType
	}
	if err := h.agent.Emails.UpdateEmailSettings(r.Context(), emailID, settings); err != nil {
		writeError(w, http.StatusInternalServerError, "Failed to update settings: "+err.Error())
		return
	}
	if req.SendListID != "" {
		if _, err := h.agent.SetEmailSendList(r.Context(), emailID, []string{req.SendListID}, req.SuppressionListIDs); err != nil {
			writeError(w, http.StatusInternalServerError, "Failed to apply send list: "+err.Error())
			return
		}
	}

	// UTM resolution — never errors, best-effort only.
	_, _ = h.agent.Emails.ResolveUTMCampaign(r.Context(), req.CloneBaseID, req.EmailName)

	subject := req.Subject
	previewText := req.PreviewText
	contentApplied := false
	contentSource := "none"

	switch {
	case req.RawHTML != "":
		// Priority 1: raw HTML injected verbatim, no AI.
		if _, err := h.agent.Emails.UpdateEmailContent(r.Context(), emailID, domain.UpdateEmailContentInput{
			HTMLContent: req.RawHTML,
		}); err != nil {
			writeError(w, http.StatusInternalServerError, "Failed to apply content: "+err.Error())
			return
		}
		contentApplied = true
		contentSource = "doc"

	case req.EventURL != "":
		// Priority 2: scrape the event page, detect stage, generate content.
		eventDetails := h.agent.Scraper.ScrapeEventFull(req.EventURL)
		if req.EventName != "" {
			eventDetails.EventName = req.EventName
		}
		if len(req.EventDates) > 0 {
			eventDetails.EventDates = req.EventDates
		}
		if req.Location != "" {
			eventDetails.Location = req.Location
		}
		if req.Description != "" {
			eventDetails.Description = req.Description
		}

		stage := stagedetector.DetectStage(eventDetails.EventDates)

		generated, genErr := h.agent.GenerateEmailContent(r.Context(), wizardagent.GenerateEmailContentInput{
			EventDetails: eventDetails,
			Stage:        stageInputFromResult(stage),
		})
		if genErr != nil {
			writeError(w, http.StatusInternalServerError, "Content generation failed: "+genErr.Error())
			return
		}

		updateInput := domain.UpdateEmailContentInput{
			BannerURL: generated.BannerURL,
			EventURL:  req.EventURL,
		}
		if len(generated.Sections) > 0 {
			updateInput.ContentSections = sectionsToContentSections(generated.Sections)
		} else {
			updateInput.HTMLContent = generated.HTML
		}
		if _, err := h.agent.Emails.UpdateEmailContent(r.Context(), emailID, updateInput); err != nil {
			writeError(w, http.StatusInternalServerError, "Failed to apply content: "+err.Error())
			return
		}
		contentApplied = true
		contentSource = "ai"
		if generated.Subject != "" {
			subject = generated.Subject
		}
		if generated.PreviewText != "" {
			previewText = generated.PreviewText
		}

	default:
		// Priority 3: clone + settings only, no content.
	}

	writeJSON(w, http.StatusOK, model.StagingBriefResult{
		EmailID:        emailID,
		DraftURL:       draftURL,
		EmailName:      req.EmailName,
		ContentApplied: contentApplied,
		ContentSource:  contentSource,
		Subject:        subject,
		PreviewText:    previewText,
	})
}

// sectionsToContentSections adapts the wizard's loosely-typed
// model.EmailSection (map[string]any) into the domain port's
// model.ContentSection shape via a JSON round-trip — both sides already
// agree on field names (type/content/etc.), so this avoids duplicating the
// section schema in two places.
func sectionsToContentSections(sections []model.EmailSection) []model.ContentSection {
	b, err := json.Marshal(sections)
	if err != nil {
		return nil
	}
	var out []model.ContentSection
	if err := json.Unmarshal(b, &out); err != nil {
		return nil
	}
	return out
}
