package audience

import (
	"context"
	"fmt"
	"regexp"
	"strings"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
)

// QaService runs the same signal-mapping / suppression checks as the
// audience-qa skill, but against an arbitrary existing HubSpot list's real
// filterBranch (via HubSpotListClient.GetList, fetched with
// includeFilters=true) instead of build-time segment metadata — ported from
// audience_builder/qa.py.
//
// Many lists in this portal are "master lists" whose filters are entirely
// IN_LIST references to *other* lists rather than direct property
// conditions. The real signal lives in what those referenced lists are, so
// both checks resolve referenced list names (one hop) and match hints
// against those names too, not just leaf filter fields.
type QaService struct {
	lists    domain.HubSpotListClient
	portalID string
}

func NewQaService(lists domain.HubSpotListClient, portalID string) *QaService {
	return &QaService{lists: lists, portalID: portalID}
}

// Property/filterType substrings, AND referenced-list-name substrings, that
// count as a real engagement signal (event registration, page view, email/
// opt-in activity, training enrollment, subscription) rather than a bare
// geography/firmographic condition.
var engagementHints = []string{
	"custom_event", "customevent", "event_", "registrat", "attend",
	"page_view", "pageview", "web_analytics", "webanalytics", "visited",
	"email_subscription", "opt_in", "optin", "enrollment", "hs_analytics",
	"web visit", "subscri", "training", "webinar", "download", "engagement",
	"speaker",
}
var firmographicOnlyHints = []string{
	"country", "state", "region", "jobtitle", "job_title", "company",
	"industry", "hs_country", "address",
}

// Name substrings used to classify what an *exclusion* list actually is,
// since this portal has no fixed CASL/Global-Do-Not-Email list to look up by
// exact term.
var gdprHints = []string{"gdpr"}
var optOutHints = []string{"opt out", "opt-out", "optout", "global opt"}
var genericSuppressionHints = []string{
	"suppress", "exclusion", "unsubscribe", "do not email", "casl", "opt out", "opt-out",
}

var listURLRe = regexp.MustCompile(`objectLists/(\d+)`)

// ResolveListRef resolves a HubSpot list URL, bare numeric ID, or list name
// to {list_id, name, candidates}. Candidates is only populated (and ListID
// left empty) when a name search matches more than one list, so the caller
// can ask the user to disambiguate.
func (s *QaService) ResolveListRef(ctx context.Context, listRef string) (*model.ResolvedListRef, error) {
	listRef = strings.TrimSpace(listRef)
	if listRef == "" {
		return nil, fmt.Errorf("list_ref is required: %w", domain.ErrInvalidInput)
	}

	if m := listURLRe.FindStringSubmatch(listRef); m != nil {
		info, err := s.lists.GetList(ctx, m[1])
		if err != nil {
			return nil, err
		}
		return &model.ResolvedListRef{ListID: m[1], Name: info.Name}, nil
	}

	if isDigits(listRef) {
		info, err := s.lists.GetList(ctx, listRef)
		if err != nil {
			return nil, err
		}
		return &model.ResolvedListRef{ListID: listRef, Name: info.Name}, nil
	}

	results, err := s.lists.SearchLists(ctx, listRef, 20)
	if err != nil {
		return nil, err
	}
	var exact []model.ListInfo
	for _, r := range results {
		if strings.EqualFold(strings.TrimSpace(r.Name), listRef) {
			exact = append(exact, r)
		}
	}
	matches := exact
	if len(matches) == 0 {
		matches = results
	}
	if len(matches) == 0 {
		return nil, fmt.Errorf("no HubSpot list found matching %q: %w", listRef, domain.ErrNotFound)
	}
	if len(matches) > 1 && len(exact) == 0 {
		candidates := make([]model.ResolveListRefCandidate, 0, len(matches))
		for _, r := range matches {
			if r.ID == "" {
				continue
			}
			candidates = append(candidates, model.ResolveListRefCandidate{ListID: r.ID, Name: r.Name, Size: optionalSize(r.Size)})
		}
		return &model.ResolvedListRef{Candidates: candidates}, nil
	}
	best := matches[0]
	return &model.ResolvedListRef{ListID: best.ID, Name: best.Name}, nil
}

func isDigits(s string) bool {
	if s == "" {
		return false
	}
	for _, r := range s {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}

// walkFilters collects every leaf filter out of a HubSpot filterBranch tree.
func walkFilters(branch *model.FilterBranch, out *[]model.Filter) {
	if branch == nil {
		return
	}
	*out = append(*out, branch.Filters...)
	for i := range branch.FilterBranches {
		walkFilters(&branch.FilterBranches[i], out)
	}
}

func filterSignature(f model.Filter, nameByID map[string]string) string {
	parts := []string{strings.ToLower(f.FilterType), strings.ToLower(f.Property)}
	if f.ListID != "" {
		parts = append(parts, strings.ToLower(nameByID[f.ListID]))
	}
	return strings.Join(parts, " ")
}

func (s *QaService) fetchListName(ctx context.Context, listID string) string {
	info, err := s.lists.GetList(ctx, listID)
	if err != nil {
		return ""
	}
	return info.Name
}

// referencedListIDs returns the set of listIds referenced by IN_LIST filters
// with the given operator (IN_LIST or NOT_IN_LIST).
func referencedListIDs(filters []model.Filter, operator string) []string {
	seen := map[string]bool{}
	var out []string
	for _, f := range filters {
		if f.FilterType != "IN_LIST" || !strings.EqualFold(f.Operator, operator) || f.ListID == "" {
			continue
		}
		if seen[f.ListID] {
			continue
		}
		seen[f.ListID] = true
		out = append(out, f.ListID)
	}
	return out
}

func containsAny(s string, hints []string) bool {
	for _, h := range hints {
		if strings.Contains(s, h) {
			return true
		}
	}
	return false
}

func CheckSignalMapping(filters []model.Filter, nameByID map[string]string) model.QaCheckResult {
	sigs := make([]string, 0, len(filters))
	for _, f := range filters {
		sigs = append(sigs, filterSignature(f, nameByID))
	}

	hasEngagement := false
	for _, sig := range sigs {
		if containsAny(sig, engagementHints) {
			hasEngagement = true
			break
		}
	}

	onlyFirmographic := len(sigs) > 0
	for _, sig := range sigs {
		if sig != "" && !containsAny(sig, firmographicOnlyHints) {
			onlyFirmographic = false
			break
		}
	}

	if hasEngagement {
		return model.QaCheckResult{Verdict: "PASS", Findings: []model.QaFinding{}}
	}
	if len(sigs) == 0 {
		return model.QaCheckResult{Verdict: "NEEDS VERIFY", Findings: []model.QaFinding{{
			Severity: "MEDIUM",
			Message:  "List has no filter conditions to inspect (static/manual membership) — signal can't be inferred from filters alone.",
			Fix:      "Confirm manually whether membership was added based on a real engagement action.",
		}}}
	}
	if onlyFirmographic {
		return model.QaCheckResult{Verdict: "FAIL", Findings: []model.QaFinding{{
			Severity: "HIGH",
			Message:  "List filters only on geography/firmographic properties, with no engagement or opt-in signal (registration, page view, email activity).",
			Fix:      "Add an event-registration, opt-in, or page-view condition before sending, or keep this list exploratory-only.",
		}}}
	}
	return model.QaCheckResult{Verdict: "NEEDS VERIFY", Findings: []model.QaFinding{{
		Severity: "MEDIUM",
		Message:  "Could not confidently classify this list's filter conditions as engagement-based or not.",
		Fix:      "Manually review the filter conditions in HubSpot.",
	}}}
}

// collectExclusionNames returns the names of every list excluded via
// NOT_IN_LIST, plus (one hop further) the names of whatever a "Combined
// Suppression"-shaped exclusion list itself includes — compose_master_list
// applies one shared "Combined Suppression" list as the NOT_IN_LIST
// exclusion rather than the individual GDPR/opt-out lists directly, so a
// flat check of the top-level excluded list's own name would miss them.
func (s *QaService) collectExclusionNames(ctx context.Context, filters []model.Filter) []string {
	var names []string
	for _, lid := range referencedListIDs(filters, "NOT_IN_LIST") {
		if name := s.fetchListName(ctx, lid); name != "" {
			names = append(names, name)
		}
		info, err := s.lists.GetList(ctx, lid)
		if err != nil || info.FilterBranch == nil {
			continue
		}
		var subFilters []model.Filter
		walkFilters(info.FilterBranch, &subFilters)
		for _, subLid := range referencedListIDs(subFilters, "IN_LIST") {
			if subName := s.fetchListName(ctx, subLid); subName != "" {
				names = append(names, subName)
			}
		}
	}
	return names
}

func (s *QaService) checkGdprCaslSuppression(ctx context.Context, filters []model.Filter, targetsEU, targetsCA bool) model.QaCheckResult {
	rawNames := s.collectExclusionNames(ctx, filters)
	names := make([]string, len(rawNames))
	for i, n := range rawNames {
		names[i] = strings.ToLower(n)
	}

	hasGDPR := false
	hasOptOut := false
	hasAnySuppression := false
	for _, n := range names {
		if !hasGDPR && containsAny(n, gdprHints) {
			hasGDPR = true
		}
		if !hasOptOut && containsAny(n, optOutHints) {
			hasOptOut = true
		}
		if !hasAnySuppression && containsAny(n, genericSuppressionHints) {
			hasAnySuppression = true
		}
	}

	var findings []model.QaFinding
	if targetsEU && !hasGDPR {
		findings = append(findings, model.QaFinding{
			Severity: "CRITICAL",
			Message:  "No GDPR suppression list found among this list's exclusions, but this audience targets the EU.",
			Fix:      "Apply the appropriate GDPR suppression list (e.g. a brand or portfolio GDPR-suppression list) as a NOT_IN_LIST exclusion.",
		})
	} else if !hasGDPR && len(names) == 0 {
		findings = append(findings, model.QaFinding{
			Severity: "MEDIUM",
			Message:  "No GDPR suppression list found among this list's exclusions.",
			Fix:      "Confirm whether GDPR suppression is required for this audience, and apply it as an exclusion if so.",
		})
	}
	if !hasOptOut {
		findings = append(findings, model.QaFinding{
			Severity: "HIGH",
			Message:  "No Global Opt-Out(s) list found among this list's exclusions.",
			Fix:      "Apply the relevant Global Opt-Out(s) list (portfolio-wide or brand-scoped) as a NOT_IN_LIST exclusion.",
		})
	}
	if targetsCA && !hasAnySuppression {
		findings = append(findings, model.QaFinding{
			Severity: "MEDIUM",
			Message:  "This audience targets Canada, but this portal has no dedicated CASL suppression list — no suppression exclusion of any kind was found on this list.",
			Fix:      "Manually confirm Canadian contacts' consent/opt-out status is honored (e.g. via the Global Opt-Out list) before sending.",
		})
	}

	verdict := "PASS"
	hasCritical := false
	for _, f := range findings {
		if f.Severity == "CRITICAL" {
			hasCritical = true
			break
		}
	}
	if hasCritical {
		verdict = "FAIL"
	} else if len(findings) > 0 {
		verdict = "NEEDS VERIFY"
	}
	if findings == nil {
		findings = []model.QaFinding{}
	}
	return model.QaCheckResult{
		Verdict:  verdict,
		Findings: findings,
		Applied:  &model.QaSuppressionApplied{GDPR: hasGDPR, OptOut: hasOptOut},
	}
}

func CheckExclusionCompleteness(filters []model.Filter) model.QaCheckResult {
	exclusionIDs := referencedListIDs(filters, "NOT_IN_LIST")
	if len(exclusionIDs) > 0 {
		count := len(exclusionIDs)
		return model.QaCheckResult{Verdict: "PASS", Findings: []model.QaFinding{}, ExclusionCount: &count}
	}
	zero := 0
	return model.QaCheckResult{
		Verdict: "FAIL",
		Findings: []model.QaFinding{{
			Severity: "HIGH",
			Message:  "List has zero exclusion segments (no suppression, opt-out, or non-marketing exclusions).",
			Fix:      "Add the required suppression exclusions before this list is used to send.",
		}},
		ExclusionCount: &zero,
	}
}

func combineVerdicts(verdicts []string) string {
	hasFail, hasNeedsVerify := false, false
	for _, v := range verdicts {
		switch v {
		case "FAIL":
			hasFail = true
		case "NEEDS VERIFY":
			hasNeedsVerify = true
		}
	}
	if hasFail {
		return "FAIL"
	}
	if hasNeedsVerify {
		return "NEEDS VERIFY"
	}
	return "PASS"
}

// RunQaOnList fetches the list's real filterBranch, walks its filters, and
// runs all 3 QA checks against it.
func (s *QaService) RunQaOnList(ctx context.Context, listID string, targetsEU, targetsCA bool) (*model.QaResult, error) {
	info, err := s.lists.GetList(ctx, listID)
	if err != nil {
		return nil, err
	}

	var filters []model.Filter
	walkFilters(info.FilterBranch, &filters)

	inclusionIDs := referencedListIDs(filters, "IN_LIST")
	nameByID := make(map[string]string, len(inclusionIDs))
	for _, lid := range inclusionIDs {
		nameByID[lid] = s.fetchListName(ctx, lid)
	}

	signal := CheckSignalMapping(filters, nameByID)
	suppression := s.checkGdprCaslSuppression(ctx, filters, targetsEU, targetsCA)
	exclusion := CheckExclusionCompleteness(filters)

	findings := make([]model.QaFinding, 0, len(signal.Findings)+len(suppression.Findings)+len(exclusion.Findings))
	findings = append(findings, signal.Findings...)
	findings = append(findings, suppression.Findings...)
	findings = append(findings, exclusion.Findings...)

	overall := combineVerdicts([]string{signal.Verdict, suppression.Verdict, exclusion.Verdict})

	return &model.QaResult{
		ListID:     listID,
		Name:       info.Name,
		HubSpotURL: fmt.Sprintf("https://app.hubspot.com/contacts/%s/objectLists/%s/filters", s.portalID, listID),
		Checks: map[string]model.QaCheckResult{
			"signal_mapping":         signal,
			"gdpr_casl_suppression":  suppression,
			"exclusion_completeness": exclusion,
		},
		Findings: findings,
		Overall:  overall,
	}, nil
}
