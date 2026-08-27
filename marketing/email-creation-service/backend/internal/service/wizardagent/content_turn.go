package wizardagent

import (
	"context"
	"fmt"
	"strings"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/aiemailtemplates"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/stagedetector"
)

// VariantBGenerator stands in for Python's generate_ai_content.py
// (generate_variation_b_email) — a sibling module content_turn.py depends
// on that was never ported to Go in any prior phase and is out of this
// phase's explicit scope too (see this package's doc comment). Leaving
// Agent.VariantBGen nil reproduces Python's own fallback behavior for an
// import/call failure: content_turn degrades gracefully rather than
// blocking the rest of the flow.
type VariantBGenerator interface {
	GenerateVariationBEmail(ctx context.Context, aiTemplateKey string, eventData map[string]any) (*model.GeneratedContent, error)
}

// ContentAnalyzer stands in for Python's analyze_email_content.py
// (analyze_and_improve_email) — the other un-ported sibling dependency of
// content_turn.py. See VariantBGenerator's doc comment for the same
// rationale; Agent.Analyzer defaults to nil.
type ContentAnalyzer interface {
	AnalyzeAndImprove(ctx context.Context, subject, previewText, bodyHTML string) (*ContentAnalysisResult, error)
}

// ContentAnalysisResult is analyze_and_improve_email's return shape.
type ContentAnalysisResult struct {
	OverallScore    int
	ImprovedSubject string
	ImprovedPreview string
	Notes           string
}

// ContentTurn ports content_turn(session, content_input) — the PHASE 3
// flow that takes free-form user content (Google Doc URL, HTML, or plain
// text) and turns it into Variant B's staged content, while Variant A
// (already staged by clone_turn) is refreshed from the AI-template
// generator keyed off the detected funnel stage.
//
// This is a DIFFERENT Variant-A/B relationship than clone_turn's: here,
// Step 1 calls a.VariantBGen (generate_ai_content.generate_variation_b_email
// in Python — NOT this package's own GenerateAITemplateContent) against
// session.Meta["email_id"] as the base email. See this package's doc
// comment for why the two "Variant A" generators are intentionally kept
// separate rather than collapsed.
//
// Fidelity note: Python's content_turn only assigns its `messages` return
// value inside the `if variant_b_id:` branch of Step 3 — if variant_b_id is
// falsy, the bare `return output, messages` at the end of the function
// would raise a NameError in Python. Go cannot reproduce an undefined-name
// runtime error the same way, so this port falls back to returning
// session.Messages unchanged in that branch — a deliberate, flagged
// judgment call (see the phase-4 report) rather than an attempt to
// "fix" the underlying bug into something well-defined.
func (a *Agent) ContentTurn(ctx context.Context, session *model.SessionState, contentInput string) (string, []model.AgentMessage, error) {
	baseEmailID := stringMeta(session.Meta, "email_id")
	if baseEmailID == "" {
		baseEmailID = session.EmailID
	}

	eventDetails, _ := session.Meta["event_details"].(model.ScrapedEventFull)
	stageResult := stagedetector.DetectStage(eventDetails.EventDates)
	aiTemplateKey := aiemailtemplates.MapFunnelStageToAITemplate(stageResult.Name)
	if v := stringMeta(session.Meta, "ai_template_key"); v != "" {
		aiTemplateKey = v
	}
	if aiTemplateKey == "" {
		aiTemplateKey = "CFP Launch"
	}

	// === STEP 1: Variant A refresh via the (possibly nil) VariantBGen hook ===
	variantAData := map[string]any{}
	if a.VariantBGen != nil {
		eventData := map[string]any{
			"event_name":  eventDetails.EventName,
			"location":    eventDetails.Location,
			"event_dates": strings.Join(eventDetails.EventDates, ", "),
		}
		gen, err := a.VariantBGen.GenerateVariationBEmail(ctx, aiTemplateKey, eventData)
		if err == nil && gen != nil {
			_, _ = a.Emails.UpdateEmailContent(ctx, baseEmailID, contentInputToUpdate(gen, eventDetails))
			variantAData["subject"] = gen.Subject
			variantAData["preview_text"] = gen.PreviewText
		}
		// A failure here is non-fatal by design (each sub-step in Python's
		// Step 1 is independently wrapped in its own try/except) — the rest
		// of the flow proceeds regardless.
	}

	// === STEP 2: create Variant B via create_ab_variation, non-fatal on failure ===
	variantBID := ""
	baseSubject := stringMeta(variantAData, "subject")
	if baseSubject == "" {
		if e, err := a.Emails.GetEmailDetails(ctx, baseEmailID); err == nil && e != nil {
			baseSubject = e.Subject
		}
	}
	if summary, err := a.Emails.CreateABVariation(ctx, baseEmailID, "Variant B - "+baseSubject); err == nil && summary != nil {
		variantBID = summary.ID
		allowSessionEmail(session, variantBID)
	}

	// === STEP 3: restore Variant B subject, then run the REAL agentic loop ===
	messages := session.Messages
	if variantBID != "" {
		_ = a.executeTool(ctx, session, "update_email_settings", map[string]any{
			"email_id": variantBID,
			"subject":  baseSubject,
		})

		prompt := fmt.Sprintf(`The user has provided new content for this email. Content input:

%s

Steps:
1. Call fetch_content with this content_input to convert it into clean email HTML.
2. Call update_email_content with email_id=%q and the resulting html_content.
3. Reply with a short confirmation that the content was applied.`, contentInput, variantBID)

		_, updated, err := a.RunTurn(ctx, session, session.Messages, prompt)
		if err == nil {
			messages = updated
		}
	}
	session.Messages = messages

	// === STEP 3.5 (non-critical): analyze + improve, using GetEmailContentText
	// as the substitute for Python's get_email_details (Go's EmailDetails
	// lacks preview/html fields; GetEmailContentText carries subject/
	// preview_text/body_html instead — a documented approximation). ===
	analysisSummary := ""
	if variantBID != "" && a.Analyzer != nil {
		if content, err := a.Emails.GetEmailContentText(ctx, variantBID); err == nil && content != nil {
			analysis, aerr := a.Analyzer.AnalyzeAndImprove(ctx, content.Subject, content.PreviewText, content.BodyHTML)
			if aerr == nil && analysis != nil {
				analysisSummary = fmt.Sprintf("Content quality score: %d/10.", analysis.OverallScore)
				if analysis.OverallScore < 8 && analysis.ImprovedSubject != "" {
					settingsUpdate := map[string]any{"email_id": variantBID, "subject": analysis.ImprovedSubject}
					if analysis.ImprovedPreview != "" {
						settingsUpdate["preview_text"] = analysis.ImprovedPreview
					}
					_ = a.executeTool(ctx, session, "update_email_settings", settingsUpdate)
				}
			}
		}
	}

	// === STEP 4: build the final output ===
	output := buildContentTurnSummary(contentTurnSummaryInput{
		BaseEmailID:     baseEmailID,
		VariantBID:      variantBID,
		AITemplateKey:   aiTemplateKey,
		AnthropicKeySet: a.AnthropicAPIKeySet,
		AnalysisSummary: analysisSummary,
		VariantASubject: stringMeta(variantAData, "subject"),
		HasVariantA:     len(variantAData) > 0,
	})

	return output, messages, nil
}

func contentInputToUpdate(gen *model.GeneratedContent, eventDetails model.ScrapedEventFull) domain.UpdateEmailContentInput {
	return domain.UpdateEmailContentInput{
		HTMLContent:     gen.BodyHTML,
		BannerURL:       gen.BannerURL,
		EventURL:        eventDetails.Links.Register,
		ContentSections: emailSectionsToContentSections(gen.Sections),
	}
}

type contentTurnSummaryInput struct {
	BaseEmailID     string
	VariantBID      string
	AITemplateKey   string
	AnthropicKeySet bool
	AnalysisSummary string
	VariantASubject string
	HasVariantA     bool
}

// buildContentTurnSummary ports content_turn's final `output` string: a
// side-by-side comparison, status blocks, the analysis section, a
// conditional "template-only mode" warning line (only shown when no
// Anthropic API key is configured), and the 3-branch final block for
// both-variants / only-A / neither.
func buildContentTurnSummary(in contentTurnSummaryInput) string {
	var b strings.Builder

	switch {
	case in.BaseEmailID != "" && in.VariantBID != "":
		b.WriteString("Content applied to both variants.\n")
		if in.HasVariantA {
			fmt.Fprintf(&b, "Variant A refreshed (%s): %s\n", in.AITemplateKey, in.VariantASubject)
		}
		fmt.Fprintf(&b, "Variant B (your content) staged on email %s.\n", in.VariantBID)
	case in.BaseEmailID != "":
		b.WriteString("Content applied to the base email. Variant B could not be created (create_ab_variation failed).\n")
	default:
		b.WriteString("No base email was available for this session — content could not be staged.\n")
	}

	if in.AnalysisSummary != "" {
		fmt.Fprintf(&b, "\n%s\n", in.AnalysisSummary)
	}

	if !in.AnthropicKeySet {
		b.WriteString("\n⚠️ Mode: template-only (no ANTHROPIC_API_KEY configured) — content generation used template fallbacks only.\n")
	}

	return b.String()
}
