package wizardagent

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/abtest"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/eventbrands"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/stagedetector"
)

// CloneTurnInput bundles clone_turn's optional user-supplied overrides.
type CloneTurnInput struct {
	Subject     *string
	PreviewText *string
	SendListID  *string
}

// CloneTurnResult carries everything clone_turn's final text block reports,
// for the HTTP layer to build model.CloneResponse from.
type CloneTurnResult struct {
	VariantAEmailID  string
	VariantADraftURL string
	VariantBEmailID  string
	VariantBDraftURL string
	ValidationPassed bool
	ValidationIssues []string
}

// CloneTurn ports clone_turn — the most complex turn in the pipeline. It
// bypasses the agentic tool-calling loop entirely: every HubSpot write here
// is issued directly (via executeTool for the safety-gated calls, and
// directly against a.Emails for the ones Python's clone_turn itself
// bypasses _execute_tool for, e.g. the Variant A content write before
// validation) rather than letting the LLM decide what to call next. Its
// return value is likewise synthesized directly rather than being the
// model's own final answer — see the trailing session.Messages append
// below.
//
// Step sequence (mirrors Python's numbered STEP comments):
//  1. Clone the source email as Variant A.
//  2. Generate + apply Variant A ("AI Template") content, validate, retry
//     once WITHOUT re-validating after the retry.
//  3. Create Variant B via HubSpot's create_ab_variation API (the only real
//     "A/B" primitive HubSpot exposes for marketing email).
//  4. Restore Variant B's subject/preview and apply its content.
//  5. Validate Variant B, retry once WITH re-validation after the retry
//     (unlike step 2).
//  6. Apply the send list LAST, to the master (Variant A) email only.
func (a *Agent) CloneTurn(ctx context.Context, session *model.SessionState, in CloneTurnInput) (string, []model.AgentMessage, error) {
	// Resets the per-session write-allowlist exactly as Python resets its
	// (process-global) _session_email_id/_session_email_ids_allowed at the
	// top of clone_turn.
	session.EmailIDsAllowed = map[string]bool{}

	brand := brandHistoryFromSession(session)
	sourceID := stringMeta(session.Meta, "source_email_id")
	if sourceID == "" {
		if v, ok := brand["last_email_id"].(string); ok {
			sourceID = v
		}
	}
	if sourceID == "" {
		return "", nil, fmt.Errorf("clone_turn: no source email available to clone (call plan first)")
	}

	eventDetails, _ := session.Meta["event_details"].(model.ScrapedEventFull)
	stage := detectSessionStage(session, eventDetails)

	emailName := stringMeta(session.Meta, "email_name")
	if emailName == "" {
		emailName = defaultEmailName(eventDetails.EventName, stage.Name)
	}

	variantID := stringMeta(session.Meta, "selected_variant_id")
	variantReason := stringMeta(session.Meta, "selected_variant_reason")
	if variantID == "" {
		if extracted, ok := ExtractVariantIDFromMessages(session.Messages); ok {
			variantID = extracted
		} else {
			variantID, variantReason = recommendVariantStrategy(stage.Name, stage.DaysToEvent, "tech")
		}
	}

	bestPractice, _, _ := recommendBestPracticeTemplateReason(stringMeta(session.Meta, "campaign_type"), nil)

	// --- Subject/preview priority chain: explicit override > selected
	// variant's filled template > best-practice template > event name. ---
	subject := ""
	if in.Subject != nil && *in.Subject != "" {
		subject = *in.Subject
	}
	previewText := ""
	if in.PreviewText != nil && *in.PreviewText != "" {
		previewText = *in.PreviewText
	}
	if subject == "" || previewText == "" {
		eventDataMap := map[string]any{
			"event_name":  eventDetails.EventName,
			"event_dates": strings.Join(eventDetails.EventDates, ", "),
			"location":    eventDetails.Location,
		}
		if s, p, ok := getVariantSubjectPreview(stage.Name, variantID, eventDataMap); ok {
			if subject == "" {
				subject = s
			}
			if previewText == "" {
				previewText = p
			}
		}
	}
	if subject == "" {
		subject = emailName
	}

	// --- Send-list auto-detection priority chain: explicit override >
	// brand history's send list > nothing (left for a later /api/set-send-list
	// call). ---
	sendListID := ""
	if in.SendListID != nil && *in.SendListID != "" {
		sendListID = *in.SendListID
	} else if ids, ok := brand["send_list_ids"].([]string); ok && len(ids) > 0 {
		sendListID = ids[0]
	}

	// === STEP 1: clone the source email as Variant A ===
	cloneResultJSON := a.executeTool(ctx, session, "clone_email", map[string]any{
		"source_email_id": sourceID,
		"clone_name":      emailName,
	})
	cloneResult, cloneErr := decodeJSONMap(cloneResultJSON)
	if cloneErr != nil {
		return "", nil, fmt.Errorf("clone_turn: clone_email returned unparseable JSON: %w", cloneErr)
	}
	if errMsg, isErr := cloneResult["error"].(string); isErr {
		return "", nil, fmt.Errorf("clone_turn: clone_email failed: %s", errMsg)
	}
	variantAID, _ := cloneResult["email_id"].(string)
	variantADraftURL, _ := cloneResult["draft_url"].(string)

	// --- Shared assets/context — both variants describe the same event, so
	// Variant A reuses Variant B's already-uploaded hero banner and sponsor
	// logos (computed earlier by /api/generate-content and stashed in
	// session.Meta) rather than re-uploading them here. ---
	bannerURL := stringMeta(session.Meta, "banner_url")
	sponsorsList, _ := session.Meta["sponsors"].([]model.Sponsor)

	// === Variant A content generation + apply + validate (STEP 2) ===
	sentByOrg := resolveSentByOrg(eventDetails.BrandName)

	aiContent := a.GenerateAITemplateContent(ctx, eventDetails, stage, bannerURL, sponsorsList)
	variantASubject, variantAPreview := subject, previewText

	_ = a.executeTool(ctx, session, "update_email_settings", map[string]any{
		"email_id":     variantAID,
		"subject":      variantASubject,
		"preview_text": variantAPreview,
	})

	variantAValid := false
	var variantAIssues []string
	if aiContent.Mode == "ai-generated" {
		_, contentErr := a.Emails.UpdateEmailContent(ctx, variantAID, domain.UpdateEmailContentInput{
			HTMLContent:     aiContent.BodyHTML,
			BannerURL:       aiContent.BannerURL,
			EventURL:        eventDetails.Links.Register,
			ContentSections: emailSectionsToContentSections(aiContent.Sections),
			SentByOrg:       sentByOrg,
		})
		if contentErr == nil {
			validation, vErr := a.Emails.ValidateStagedEmail(ctx, variantAID, aiContent.BannerURL != "", len(aiContent.Sections))
			if vErr == nil && validation != nil {
				variantAValid = validation.Valid
				variantAIssues = validation.Issues
			}
			if vErr != nil || (validation != nil && !validation.Valid) {
				// One retry — NOT re-validated afterward, exactly as Python's
				// Variant A retry path.
				_, _ = a.Emails.UpdateEmailContent(ctx, variantAID, domain.UpdateEmailContentInput{
					HTMLContent:     aiContent.BodyHTML,
					BannerURL:       aiContent.BannerURL,
					EventURL:        eventDetails.Links.Register,
					ContentSections: emailSectionsToContentSections(aiContent.Sections),
					SentByOrg:       sentByOrg,
				})
			}
		}
	}

	// === STEP 3: create Variant B via HubSpot's create_ab_variation ===
	variantBSummary, abErr := a.Emails.CreateABVariation(ctx, variantAID, emailName+" (Variant B)")
	variantBID := ""
	if abErr == nil && variantBSummary != nil {
		variantBID = variantBSummary.ID
		allowSessionEmail(session, variantBID)
	}
	contentTargetID := variantBID
	if contentTargetID == "" {
		contentTargetID = variantAID
	}

	bestPracticeTemplateKey := ""
	bestPracticeQuality := 0
	variantBSubject, variantBPreview := subject, previewText
	if bestPractice != nil && bestPractice.Template != nil {
		bestPracticeTemplateKey = bestPractice.Key
		bestPracticeQuality = bestPractice.QualityRating
	}

	// === STEP 4: restore Variant B subject/preview + apply its content ===
	_ = a.executeTool(ctx, session, "update_email_settings", map[string]any{
		"email_id":     contentTargetID,
		"subject":      variantBSubject,
		"preview_text": variantBPreview,
	})

	// banner_url/sponsors_list/event_url/sent_by_org were already computed
	// above (shared with Variant A); Variant B's content itself is NOT
	// regenerated here — it reuses whatever /api/generate-content already
	// produced (and the user may have since edited via /api/update-sections),
	// exactly as Python's clone_turn reads session.meta["sections"]/
	// ["body_html"] rather than calling generate_email_content again.
	sections, _ := session.Meta["sections"].([]model.EmailSection)
	bodyHTML := stringMeta(session.Meta, "body_html")
	if bodyHTML == "" {
		bodyHTML = stringMeta(session.Meta, "generated_html")
	}

	contentApplied := false
	variantBValid := false
	var variantBIssues []string
	if len(sections) > 0 || bodyHTML != "" {
		htmlContent := bodyHTML
		if len(sections) > 0 {
			htmlContent = ""
		}
		_, contentErr := a.Emails.UpdateEmailContent(ctx, contentTargetID, domain.UpdateEmailContentInput{
			HTMLContent:     htmlContent,
			BannerURL:       bannerURL,
			EventURL:        eventDetails.Links.Register,
			ContentSections: emailSectionsToContentSections(sections),
			SentByOrg:       sentByOrg,
		})
		if contentErr == nil {
			contentApplied = true
		}

		// === STEP 5: validate Variant B, retry once WITH re-validation ===
		if contentErr == nil {
			validation, vErr := a.Emails.ValidateStagedEmail(ctx, contentTargetID, bannerURL != "", len(sections))
			if vErr == nil && validation != nil {
				variantBValid = validation.Valid
				variantBIssues = validation.Issues
			}
			if vErr != nil || (validation != nil && !validation.Valid) {
				_, _ = a.Emails.UpdateEmailContent(ctx, contentTargetID, domain.UpdateEmailContentInput{
					HTMLContent:     htmlContent,
					BannerURL:       bannerURL,
					EventURL:        eventDetails.Links.Register,
					ContentSections: emailSectionsToContentSections(sections),
					SentByOrg:       sentByOrg,
				})
				validation, vErr = a.Emails.ValidateStagedEmail(ctx, contentTargetID, bannerURL != "", len(sections))
				if vErr == nil && validation != nil {
					variantBValid = validation.Valid
					variantBIssues = validation.Issues
				}
			}
		}
	}

	// === STEP 6: apply the send list LAST, to the master (Variant A) email only ===
	if sendListID != "" {
		if _, err := a.setEmailSendList(ctx, variantAID, []string{sendListID}, suppressionListIDsFromBrand(brand)); err != nil {
			variantAIssues = append(variantAIssues, "send list: "+err.Error())
		}
	}

	var variantBDraftURL string
	if variantBSummary != nil {
		variantBDraftURL = fmt.Sprintf("https://app.hubspot.com/email/%s/edit/%s/settings", a.PortalID, variantBID)
	}

	// contentApplied mirrors agent.py's Variant B `content_applied` flag —
	// true only once Variant B's (or, when create_ab_variation failed, the
	// master's) content patch itself succeeded, independent of whether the
	// subsequent validation passed. (Computed above, next to the patch call.)
	if !contentApplied {
		variantBIssues = append([]string{"Content was not applied to the email"}, variantBIssues...)
	}

	// Persist final flags into session.Meta, exactly as Python stashes them
	// (session.meta["content_applied"/"validation_passed"/"validation_issues"/
	// "variant_a_draft_url"/"variant_b_draft_url"]) for the HTTP handler
	// (main.py's /api/clone) to read back verbatim.
	session.Meta["variant_a_email_id"] = variantAID
	session.Meta["variant_b_email_id"] = variantBID
	session.Meta["email_id"] = variantAID
	session.Meta["content_applied"] = contentApplied
	session.Meta["validation_passed"] = variantBValid
	session.Meta["validation_issues"] = variantBIssues
	session.Meta["variant_a_draft_url"] = variantADraftURL
	session.Meta["variant_b_draft_url"] = variantBDraftURL
	session.EmailID = variantAID
	session.DraftURL = variantADraftURL
	session.Phase = "cloned"

	text := buildCloneTurnSummary(cloneTurnSummaryInput{
		VariantAID:       variantAID,
		VariantADraftURL: variantADraftURL,
		VariantASubject:  variantASubject,
		VariantAValid:    variantAValid,
		AITemplateMode:   aiContent.Mode,
		AITemplateError:  aiContent.Error,
		VariantBID:       variantBID,
		VariantBDraftURL: variantBDraftURL,
		VariantBSubject:  variantBSubject,
		VariantBValid:    variantBValid,
		VariantBIssues:   variantBIssues,
		TemplateKey:      bestPracticeTemplateKey,
		QualityRating:    bestPracticeQuality,
		VariantChosenID:  variantID,
		VariantReason:    variantReason,
	})

	// Bypasses the LLM entirely for the return value: appends a synthetic
	// "I approve the plan." user turn plus this function's own text as the
	// assistant turn, exactly as Python's
	// `return text, session.messages + [{"role":"user",...},{"role":"assistant",...}]`.
	updated := append(append([]model.AgentMessage{}, session.Messages...),
		model.AgentMessage{Role: "user", Content: "I approve the plan."},
		model.AgentMessage{Role: "assistant", Content: text},
	)
	session.Messages = updated

	return text, updated, nil
}

func brandHistoryFromSession(session *model.SessionState) map[string]any {
	if brand, ok := session.Meta["brand_history"].(map[string]any); ok {
		return brand
	}
	if brand, ok := ExtractBrandHistoryFromMessages(session.Messages); ok {
		return brand
	}
	return map[string]any{}
}

func stringMeta(meta map[string]any, key string) string {
	if v, ok := meta[key].(string); ok {
		return v
	}
	return ""
}

func detectSessionStage(session *model.SessionState, eventDetails model.ScrapedEventFull) stagedetector.Result {
	if stageName := stringMeta(session.Meta, "stage_name"); stageName != "" {
		if r, ok := session.Meta["stage_result"].(stagedetector.Result); ok {
			return r
		}
		_ = stageName
	}
	return stagedetector.DetectStage(eventDetails.EventDates)
}

// defaultEmailName ports clone_turn's fallback naming: builds the
// "<YY>Q<N> - <EventName>" prefix from the current quarter when no explicit
// email_name was supplied.
func defaultEmailName(eventName, stageName string) string {
	now := time.Now()
	yy := now.Format("06")
	q := (int(now.Month())-1)/3 + 1
	suffix := "Update"
	switch {
	case strings.Contains(stageName, "Announcement"), strings.Contains(stageName, "Launch"):
		suffix = "Invite"
	case strings.Contains(stageName, "Countdown"), strings.Contains(stageName, "Final"):
		suffix = "Last Chance"
	case strings.Contains(stageName, "Newsletter"):
		suffix = "Newsletter"
	}
	if eventName == "" {
		eventName = "Event"
	}
	return fmt.Sprintf("%sQ%d - %s - %s", yy, q, eventName, suffix)
}

// resolveSentByOrg ports the "The Linux Foundation" -> "The Linux Foundation
// Events" rewrite clone_turn applies to lookup_event_brand's result before
// passing it as UpdateEmailContentInput.SentByOrg.
func resolveSentByOrg(brandName string) string {
	entry, ok := eventbrands.LookupEventBrand(brandName)
	name := brandName
	if ok {
		name = entry.BrandName
	}
	if name == "The Linux Foundation" {
		return "The Linux Foundation Events"
	}
	return name
}

func suppressionListIDsFromBrand(brand map[string]any) []string {
	if arr, ok := brand["suppression_list_ids"].([]string); ok {
		return arr
	}
	return nil
}

func emailSectionsToContentSections(sections []model.EmailSection) []model.ContentSection {
	out := make([]model.ContentSection, 0, len(sections))
	for _, s := range sections {
		cs := model.ContentSection{}
		if v, ok := s["type"].(string); ok {
			cs.Type = v
		}
		if v, ok := s["html"].(string); ok {
			cs.HTML = v
		}
		if v, ok := s["text"].(string); ok {
			cs.Text = v
		}
		if v, ok := s["background_color"].(string); ok {
			cs.BackgroundColor = v
		}
		if v, ok := s["destination"].(string); ok {
			cs.Destination = v
		}
		if v, ok := s["color"].(string); ok {
			cs.Color = v
		}
		if v, ok := s["url"].(string); ok {
			cs.URL = v
		}
		if v, ok := s["src"].(string); ok {
			cs.Src = v
		}
		if v, ok := s["alt"].(string); ok {
			cs.Alt = v
		}
		out = append(out, cs)
	}
	return out
}

type cloneTurnSummaryInput struct {
	VariantAID       string
	VariantADraftURL string
	VariantASubject  string
	VariantAValid    bool
	AITemplateMode   string
	AITemplateError  string

	VariantBID       string
	VariantBDraftURL string
	VariantBSubject  string
	VariantBValid    bool
	VariantBIssues   []string

	TemplateKey   string
	QualityRating int

	VariantChosenID string
	VariantReason   string
}

// buildCloneTurnSummary ports the 3-branch final `text` clone_turn builds
// (both variants staged / only Variant A / neither), including the A/B
// comparison block and manual A/B-test-setup instructions.
func buildCloneTurnSummary(in cloneTurnSummaryInput) string {
	var b strings.Builder

	switch {
	case in.VariantAID != "" && in.VariantBID != "":
		fmt.Fprintf(&b, "Staged both variants for \"%s\".\n\n", in.VariantASubject)
		fmt.Fprintf(&b, "Variant A (User Content / AI Template): %s\n", in.VariantADraftURL)
		if in.AITemplateMode == "failed" {
			fmt.Fprintf(&b, "  (Variant A content generation failed: %s — the email was still cloned and its settings applied.)\n", in.AITemplateError)
		}
		fmt.Fprintf(&b, "Variant B (Best-Practice Template %s): %s\n", in.TemplateKey, in.VariantBDraftURL)
		if !in.VariantBValid && len(in.VariantBIssues) > 0 {
			fmt.Fprintf(&b, "  Validation issues: %s\n", strings.Join(in.VariantBIssues, "; "))
		}
		b.WriteString(formatABTestComparison(
			map[string]any{"subject": in.VariantASubject, "type": "User-Created Content"},
			map[string]any{"subject": in.VariantBSubject, "template_key": in.TemplateKey, "quality_rating": fmt.Sprint(in.QualityRating)},
		))
		setup := abtest.DocumentABTestSetup(in.VariantAID, in.VariantASubject, in.VariantBID, in.VariantBSubject, in.TemplateKey, in.QualityRating)
		b.WriteString(setup.Instructions)

	case in.VariantAID != "":
		fmt.Fprintf(&b, "Staged Variant A for \"%s\": %s\n", in.VariantASubject, in.VariantADraftURL)
		b.WriteString("Variant B could not be created (create_ab_variation failed) — only one email is staged. You can still edit and send it directly.\n")

	default:
		b.WriteString("Cloning failed — no email was staged.\n")
	}

	if in.VariantChosenID != "" {
		fmt.Fprintf(&b, "\nMessaging variant used: %s", in.VariantChosenID)
		if in.VariantReason != "" {
			fmt.Fprintf(&b, " (%s)", in.VariantReason)
		}
		b.WriteString("\n")
	}

	return b.String()
}
