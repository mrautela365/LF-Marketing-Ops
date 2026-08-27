// plan.go ports main.py's _create_plan_impl — the shared orchestration
// behind both POST /api/plan (blocking) and POST /api/plan-start (streamed).
// It lives in this package (not cmd/emailcreationskill) because it needs
// direct access to the agent's PlanTurn/AISelectSourceEmail/claudeText
// machinery and to sectionsToHTML/buildEmailPreview's package-private
// helpers used later in the flow.
package wizardagent

import (
	"context"
	"encoding/json"
	"fmt"
	"regexp"
	"strconv"
	"strings"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/eventbrands"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/stagedetector"
)

// PlanEmit streams one human-readable "brief" line, ported from
// _create_plan_impl's emit(text) callback. A nil PlanEmit is treated as a
// no-op, matching Python's `emit=lambda *a, **k: None` default.
type PlanEmit func(text string)

func emitLine(emit PlanEmit, text string) {
	if emit != nil {
		emit(text)
	}
}

// stageKeywordMap ports _STAGE_KW_MAP verbatim — the per-stage keyword list
// used to find a stage-specific content reference email in HubSpot.
var stageKeywordMap = map[string][]string{
	"Event Announcement":               {"announcement", "invite", "announcing"},
	"CFP Launch":                       {"cfp", "call for proposals", "call for speakers", "speak"},
	"Registration Launch":              {"registration", "register", "cfp open", "registration live"},
	"Co-Located Events + CFP Reminder": {"cfp", "co-located", "colocated", "reminder"},
	"DEI & Travel Fund":                {"dei", "travel fund", "scholarship", "diversity"},
	"Schedule Announcement":            {"schedule", "keynote", "sessions", "agenda"},
	"Main Registration Push":           {"register", "reminder", "registration", "push"},
	"Final Countdown":                  {"last chance", "last call", "final", "countdown", "closing", "closes", "deadline"},
	"Event Week":                       {"reminder", "event week", "logistics", "venue", "join us"},
	"Thank You + Survey":               {"thank you", "thanks", "survey", "feedback", "post-event"},
	"Content & Recordings Release":     {"recording", "content", "recap", "slides", "session"},
	"Next Event CFP Teaser":            {"cfp", "upcoming", "next event", "teaser", "save the date"},
	"Community Nurture":                {"community", "newsletter", "update", "nurture"},
	"Invite":                           {"invite"},
	"Last Chance":                      {"last chance", "last call", "closes", "deadline"},
	"Reminder":                         {"reminder"},
	"Save the Date":                    {"save the date", "save-the-date"},
}

var yyqDateRe = regexp.MustCompile(`^(\d{4})-(\d{2})-(\d{2})`)

// buildDeterministicEmailName ports _build_email_name(): "<YY>Q<N> -
// <ShortBrand|Brand> - <EventName> - <Suffix>", never relying on Claude's
// prose.
func buildDeterministicEmailName(eventDates []string, shortBrandName, brandName, eventName, emailTypeOverride, stageEmailType string) string {
	yyq := ""
	for _, ds := range eventDates {
		m := yyqDateRe.FindStringSubmatch(ds)
		if m == nil {
			continue
		}
		yr, _ := strconv.Atoi(m[1])
		mo, _ := strconv.Atoi(m[2])
		yyq = fmt.Sprintf("%02dQ%d", yr%100, (mo-1)/3+1)
		break
	}
	code := shortBrandName
	if code == "" {
		code = brandName
	}
	suffix := emailTypeOverride
	if suffix == "" {
		suffix = stageEmailType
	}
	if suffix == "" {
		suffix = "Invite"
	}
	var parts []string
	for _, p := range []string{code, eventName, suffix} {
		if p != "" {
			parts = append(parts, p)
		}
	}
	body := strings.Join(parts, " - ")
	if yyq != "" && body != "" {
		return yyq + " - " + body
	}
	return body
}

// stageResultToMap ports detect_stage's returned dict shape verbatim (name,
// funnel, email_type, days_to_event, goal, cta_label, event_date_str, color,
// stage_number, timeline, marketing_strategy, content_ideas,
// industry_best_practices) — the exact keys the frontend's Stage & Content
// Overview rendering and the plan prompt's data block expect.
func stageResultToMap(r stagedetector.Result) map[string]any {
	m := map[string]any{
		"name":               r.Name,
		"funnel":             r.Funnel,
		"email_type":         r.EmailType,
		"goal":               r.Goal,
		"cta_label":          r.CTALabel,
		"event_date_str":     r.EventDateStr,
		"color":              r.Color,
		"timeline":           r.Timeline,
		"marketing_strategy": r.MarketingStrategy,
		"content_ideas":      r.ContentIdeas,
	}
	if r.DaysToEvent != nil {
		m["days_to_event"] = *r.DaysToEvent
	} else {
		m["days_to_event"] = nil
	}
	if r.StageNumber != nil {
		m["stage_number"] = *r.StageNumber
	} else {
		m["stage_number"] = nil
	}
	if r.IndustryBestPractices != nil {
		m["industry_best_practices"] = r.IndustryBestPractices
	} else {
		m["industry_best_practices"] = map[string]string{}
	}
	return m
}

// utmResolutionToMap converts model.UTMResolution to the plain
// map[string]any shape PlanResult.UTM/session.Meta["utm_params"] carry,
// using its own json tags as the single source of truth for key names.
func utmResolutionToMap(u *model.UTMResolution) map[string]any {
	if u == nil {
		return map[string]any{}
	}
	b, err := json.Marshal(u)
	if err != nil {
		return map[string]any{}
	}
	var m map[string]any
	_ = json.Unmarshal(b, &m)
	return m
}

func emailSummaryName(e model.EmailSummary) string { return e.Name }

// addRef appends (id, name) to refs if id is non-empty and not already
// present, capping at 3 — ports the _add_ref/_ranked_refs de-dup + cap logic.
func addRef(refs *[]model.SourceEmailRef, id, name string) {
	if id == "" || len(*refs) >= 3 {
		return
	}
	for _, r := range *refs {
		if r.ID == id {
			return
		}
	}
	*refs = append(*refs, model.SourceEmailRef{ID: id, Name: name})
}

// CreatePlan ports _create_plan_impl. The caller is responsible for creating
// the session (session_store.create()) — mirroring the Python function's
// own `session = session_store.create()` call would require this package to
// depend on the infrastructure/memory store, which every other turn in this
// package deliberately avoids; callers already hold a *model.SessionState by
// the time they reach clone/chat/content, so the HTTP handler creates the
// session and passes it in here too.
func (a *Agent) CreatePlan(ctx context.Context, session *model.SessionState, req model.PlanRequest, modeName string, emit PlanEmit) (*model.PlanResult, error) {
	// --- Step A: full event scrape ---
	emitLine(emit, "🔎 Reading the event page…")
	eventDetails := a.Scraper.ScrapeEventFull(req.URL)
	session.Meta["event_details"] = eventDetails
	session.Meta["url_data"] = eventDetails

	rawEvent := eventDetails.EventName
	location := eventDetails.Location
	if rawEvent != "" {
		if location != "" {
			emitLine(emit, fmt.Sprintf("📄 Event detected: %s · %s", rawEvent, location))
		} else {
			emitLine(emit, fmt.Sprintf("📄 Event detected: %s", rawEvent))
		}
	}

	emitLine(emit, "🏷️ Identifying brand…")
	var brandName, shortBrandName, eventShortName, eventName string
	if known, ok := eventbrands.LookupEventBrand(rawEvent); ok {
		brandName = known.BrandName
		shortBrandName = known.ShortBrandName
		eventShortName = known.EventShortName
		eventName = known.EventName
		session.Meta["short_brand_name"] = shortBrandName
		session.Meta["event_short_name"] = eventShortName
	} else {
		brandName = eventDetails.BrandName
		eventName = rawEvent
	}

	emailTypeOverride := strings.TrimSpace(req.EmailType)
	var candidates []model.EmailSummary

	// --- AI-driven source email selection ---
	if brandName != "" || shortBrandName != "" {
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

		emitLine(emit, fmt.Sprintf("📚 Searching HubSpot for past %s campaigns…", firstNonEmpty(brandName, shortBrandName)))
		var err error
		candidates, err = a.Emails.GetBrandEmails(ctx, domain.GetBrandEmailsOptions{
			ShortBrandName:  shortBrandName,
			BrandName:       brandName,
			EventShortNames: eventShortNames,
			EventURL:        req.URL,
		})
		if err != nil {
			candidates = nil
		}
		emitLine(emit, fmt.Sprintf("📬 Found %d past campaign email(s) to learn from.", len(candidates)))

		if len(candidates) > 0 {
			aiPool, _ := eventbrands.FilterCandidatesByLocale(candidates, eventName, location, emailSummaryName)

			emitLine(emit, fmt.Sprintf("🤖 AI reviewing %d candidate(s) to pick the best source email…", len(aiPool)))
			cands := make([]SourceEmailCandidate, len(aiPool))
			for i, e := range aiPool {
				cands[i] = SourceEmailCandidate{EmailID: e.ID, Name: e.Name, PublishDate: e.PublishDate}
			}
			selectedID, ok := a.AISelectSourceEmail(ctx, eventName, eventShortName, location, cands, req.URL, 5)
			if ok {
				var selected *model.EmailSummary
				for i := range aiPool {
					if aiPool[i].ID == selectedID {
						selected = &aiPool[i]
						break
					}
				}
				if selected != nil {
					emitLine(emit, fmt.Sprintf("✅ Source email selected: %s", firstNonEmpty(selected.Name, "(unnamed)")))
					session.Meta["brand_history"] = map[string]any{
						"found":                true,
						"matched_email_id":     selected.ID,
						"matched_email_name":   selected.Name,
						"from_name":            selected.From.FromName,
						"from_address":         selected.From.ReplyTo,
						"email_type":           firstNonEmpty(selected.Type, "BATCH_EMAIL"),
						"suppression_list_ids": unionStrings(selected.To.ContactIlsLists.Exclude, selected.To.ContactLists.Exclude),
						"included_list_ids":    unionStrings(selected.To.ContactIlsLists.Include, selected.To.ContactLists.Include),
					}
				}
			}
		}
	}

	// --- Keyword-scoring fallback ---
	if _, has := session.Meta["brand_history"]; !has && brandName != "" && eventName != "" {
		match, err := a.Emails.SearchEmailsForEvent(ctx, domain.SearchEmailsForEventOptions{
			BrandName:      brandName,
			EventName:      eventName,
			Location:       location,
			ShortBrandName: shortBrandName,
			EventShortName: eventShortName,
			EmailType:      emailTypeOverride,
		})
		if err == nil && match != nil && match.Found {
			b, _ := json.Marshal(match)
			var bh map[string]any
			_ = json.Unmarshal(b, &bh)
			session.Meta["brand_history"] = bh
		}
	}

	// --- Step B: stage detection ---
	emitLine(emit, "📅 Detecting campaign stage from the event timeline…")
	stage := stagedetector.DetectStage(eventDetails.EventDates)
	session.Meta["stage_result"] = stage
	session.Meta["stage_name"] = stage.Name
	stageMap := stageResultToMap(stage)
	session.Meta["stage_info"] = stageMap
	daysStr := "?"
	if stage.DaysToEvent != nil {
		daysStr = fmt.Sprint(*stage.DaysToEvent)
	}
	emitLine(emit, fmt.Sprintf("🎯 Stage: %s (%s)", stage.Name, stage.Funnel))
	_ = daysStr

	// --- Deterministic email name ---
	detName := buildDeterministicEmailName(eventDetails.EventDates, shortBrandName, brandName, eventName, emailTypeOverride, stage.EmailType)
	if detName != "" {
		session.Meta["email_name"] = detName
	}

	// --- UTM campaign resolution ---
	emitLine(emit, "🔗 Resolving UTM campaign…")
	brandHistory, _ := session.Meta["brand_history"].(map[string]any)
	sourceEmailID := ""
	if brandHistory != nil {
		if v, ok := brandHistory["matched_email_id"].(string); ok {
			sourceEmailID = v
		}
		if sourceEmailID == "" {
			if v, ok := brandHistory["last_email_id"].(string); ok {
				sourceEmailID = v
			}
		}
	}
	if sourceEmailID != "" {
		session.Meta["source_email_id"] = sourceEmailID
	}
	utmRes, _ := a.Emails.ResolveUTMCampaign(ctx, sourceEmailID, stringMeta(session.Meta, "email_name"))
	utmMap := utmResolutionToMap(utmRes)
	session.Meta["utm_params"] = utmMap

	// --- Step B2: stage-specific content reference ranking (top 3) ---
	stageKeywords := stageKeywordMap[stage.Name]
	var rankedRefs []model.SourceEmailRef
	if len(stageKeywords) > 0 {
		for _, c := range candidates {
			lname := strings.ToLower(c.Name)
			matched := false
			for _, kw := range stageKeywords {
				if strings.Contains(lname, kw) {
					matched = true
					break
				}
			}
			if matched {
				addRef(&rankedRefs, c.ID, c.Name)
			}
			if len(rankedRefs) >= 3 {
				break
			}
		}
	}
	for _, c := range candidates {
		if len(rankedRefs) >= 3 {
			break
		}
		addRef(&rankedRefs, c.ID, c.Name)
	}
	if brandHistory != nil {
		mid, _ := brandHistory["matched_email_id"].(string)
		mname, _ := brandHistory["matched_email_name"].(string)
		addRef(&rankedRefs, mid, mname)
	}
	if len(rankedRefs) > 3 {
		rankedRefs = rankedRefs[:3]
	}
	if len(rankedRefs) > 0 {
		ids := make([]string, len(rankedRefs))
		for i, r := range rankedRefs {
			ids[i] = r.ID
		}
		session.Meta["content_reference_ids"] = ids
		session.Meta["content_reference_id"] = rankedRefs[0].ID
		session.Meta["content_reference_name"] = rankedRefs[0].Name
	}

	// --- Call the LLM to draft the plan text ---
	emitLine(emit, "📝 Drafting the campaign plan…")
	text, messages, err := a.PlanTurn(ctx, session, req.URL)
	if err != nil {
		return nil, err
	}
	session.Messages = messages
	session.Phase = "planning"
	session.Plan = map[string]any{"url": req.URL}

	if _, has := session.Meta["brand_history"]; !has {
		if extracted, ok := ExtractBrandHistoryFromMessages(messages); ok {
			session.Meta["brand_history"] = extracted
			brandHistory = extracted
		}
	}

	if stringMeta(session.Meta, "email_name") == "" {
		if m := backtickEmailNameRe.FindStringSubmatch(text); m != nil {
			session.Meta["email_name"] = strings.TrimSpace(m[1])
		}
	}

	emitLine(emit, "✅ Campaign plan ready.")

	var sourceEmail *model.SourceEmailRef
	if brandHistory != nil {
		eid, _ := brandHistory["matched_email_id"].(string)
		if eid == "" {
			eid, _ = brandHistory["last_email_id"].(string)
		}
		ename, _ := brandHistory["matched_email_name"].(string)
		if ename == "" {
			ename, _ = brandHistory["last_email_name"].(string)
		}
		if eid != "" {
			sourceEmail = &model.SourceEmailRef{ID: eid, Name: ename}
		}
	}

	return &model.PlanResult{
		SessionID:   session.SessionID,
		Message:     text,
		Phase:       session.Phase,
		Mode:        modeName,
		SourceEmail: sourceEmail,
		Stage:       stageMap,
		UTM:         utmMap,
	}, nil
}

var backtickEmailNameRe = regexp.MustCompile("`(2\\dQ\\d[^`]+)`")

func firstNonEmpty(vals ...string) string {
	for _, v := range vals {
		if v != "" {
			return v
		}
	}
	return ""
}
