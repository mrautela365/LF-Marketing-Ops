package wizardagent

import (
	"context"
	"encoding/json"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/emailtemplates"
)

// executeTool ports _execute_tool's dispatch switch (the safety gate itself
// lives in safety.go's checkToolSafety, called first exactly as Python
// checks _FORBIDDEN_TOOLS/_WRITE_TOOLS before the try/dispatch block).
// sessionEmailID mirrors _execute_tool's optional session_email_id
// parameter — always session.EmailID here.
func (a *Agent) executeTool(ctx context.Context, session *model.SessionState, name string, inputs map[string]any) string {
	if blocked, errJSON := checkToolSafety(name, inputs, session, session.EmailID); blocked {
		return errJSON
	}

	result, err := a.dispatchTool(ctx, session, name, inputs)
	if err != nil {
		return jsonError(err.Error())
	}
	b, merr := json.Marshal(result)
	if merr != nil {
		return jsonError(merr.Error())
	}
	return string(b)
}

func (a *Agent) dispatchTool(ctx context.Context, session *model.SessionState, name string, inputs map[string]any) (any, error) {
	str := func(key string) string {
		v, _ := inputs[key].(string)
		return v
	}
	strSlice := func(key string) []string {
		arr, _ := inputs[key].([]any)
		out := make([]string, 0, len(arr))
		for _, v := range arr {
			if s, ok := v.(string); ok {
				out = append(out, s)
			}
		}
		return out
	}

	switch name {
	case "lookup_brand_history":
		return a.lookupBrandHistory(ctx, str("brand_name"), str("email_type_hint"))

	case "clone_email":
		cloned, err := a.Emails.CloneEmail(ctx, str("source_email_id"), str("clone_name"))
		if err != nil {
			return map[string]any{"error": err.Error()}, nil
		}
		allowSessionEmail(session, cloned.EmailID)
		session.EmailID = cloned.EmailID
		session.DraftURL = cloned.DraftURL
		return map[string]any{
			"email_id":  cloned.EmailID,
			"name":      cloned.Name,
			"state":     cloned.State,
			"draft_url": cloned.DraftURL,
		}, nil

	case "update_email_settings":
		emailID := str("email_id")
		update := domain.EmailSettingsUpdate{}
		if v, ok := inputs["subject"].(string); ok {
			update.Subject = &v
		}
		if v, ok := inputs["email_type"].(string); ok {
			update.Type = &v
		}
		if v, ok := inputs["from_name"].(string); ok {
			update.FromName = &v
		}
		if v, ok := inputs["from_address"].(string); ok {
			update.ReplyTo = &v
		}
		if v, ok := inputs["preview_text"].(string); ok {
			update.PreviewText = &v
		}
		if err := a.Emails.UpdateEmailSettings(ctx, emailID, update); err != nil {
			return map[string]any{"error": err.Error()}, nil
		}
		result := map[string]any{"success": true, "email_id": emailID}
		if sendListID := str("send_list_id"); sendListID != "" {
			if _, err := a.setEmailSendList(ctx, emailID, []string{sendListID}, strSlice("suppression_list_ids")); err != nil {
				result["send_list_error"] = err.Error()
			}
		}
		return result, nil

	case "update_email_content":
		res, err := a.Emails.UpdateEmailContent(ctx, str("email_id"), domain.UpdateEmailContentInput{
			HTMLContent: str("html_content"),
		})
		if err != nil {
			return map[string]any{"error": err.Error()}, nil
		}
		return res, nil

	case "fetch_content":
		html, err := a.Scraper.PrepareContent(str("content_input"))
		if err != nil {
			return map[string]any{"error": err.Error()}, nil
		}
		return map[string]any{"html": html, "length": len(html)}, nil

	case "search_hubspot_lists":
		lists, err := a.Lists.SearchListsByName(ctx, str("search_term"), 10)
		if err != nil {
			return map[string]any{"error": err.Error()}, nil
		}
		return map[string]any{"lists": lists}, nil

	case "fetch_url":
		full := a.Scraper.ScrapeEventFull(str("url"))
		return full, nil

	case "search_emails_for_event":
		match, err := a.Emails.SearchEmailsForEvent(ctx, domain.SearchEmailsForEventOptions{
			BrandName:      str("brand_name"),
			EventName:      str("event_name"),
			Location:       str("location"),
			ShortBrandName: str("short_brand_name"),
			EventShortName: str("event_short_name"),
			EmailType:      str("email_type"),
		})
		if err != nil {
			return map[string]any{"error": err.Error()}, nil
		}
		return match, nil

	case "get_variant_strategies":
		strategies, ok := emailtemplates.ListVariantStrategies(str("stage_name"))
		if !ok {
			return map[string]any{"error": "no variants for stage", "stage_name": str("stage_name")}, nil
		}
		return map[string]any{"stage_name": str("stage_name"), "variants": strategies}, nil

	case "select_template_variant":
		stageName, variantID := str("stage_name"), str("variant_id")
		v, ok := emailtemplates.GetTemplateVariant(stageName, variantID)
		if !ok {
			return map[string]any{"error": "variant not found", "stage_name": stageName, "variant_id": variantID}, nil
		}
		if session.Meta == nil {
			session.Meta = map[string]any{}
		}
		session.Meta["selected_variant_id"] = variantID
		session.Meta["selected_variant_reason"] = str("reason")
		return map[string]any{"selected": true, "variant_id": variantID, "variant": v}, nil

	case "get_recommended_template":
		rec, reason, ok := recommendBestPracticeTemplateReason(str("campaign_type"), nil)
		if !ok {
			return map[string]any{"error": "unknown campaign_type", "campaign_type": str("campaign_type")}, nil
		}
		return map[string]any{"key": rec.Key, "quality_rating": rec.QualityRating, "source": rec.Source, "template": rec.Template, "reason": reason}, nil

	case "get_template_by_key":
		tmpl, ok := emailtemplates.GetBestPracticeTemplate(str("template_key"))
		if !ok {
			return map[string]any{"error": "unknown template_key", "template_key": str("template_key")}, nil
		}
		return tmpl, nil

	default:
		return map[string]any{"error": "Unknown tool: " + name + ". Allowed: " + allowedToolsList()}, nil
	}
}
