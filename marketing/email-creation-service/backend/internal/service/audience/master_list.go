// Package audience ports audience_builder/*.py: existing-list discovery
// support, master-list composition, last-sent lookup, and list QA. All
// deterministic (no LLM) — service depends only on domain.HubSpotListClient
// / domain.HubSpotEmailClient, never on dispatch directly.
package audience

import (
	"context"
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
)

// MasterListService composes a single "master" HubSpot list from a set of
// already-existing list IDs, via an OR-of-IN_LIST filterBranch — ported from
// audience_builder/master_list.py.
type MasterListService struct {
	lists    domain.HubSpotListClient
	portalID string
}

func NewMasterListService(lists domain.HubSpotListClient, portalID string) *MasterListService {
	return &MasterListService{lists: lists, portalID: portalID}
}

func dedupeStrings(ids []string) []string {
	seen := make(map[string]bool, len(ids))
	out := make([]string, 0, len(ids))
	for _, id := range ids {
		id = strings.TrimSpace(id)
		if id == "" || seen[id] {
			continue
		}
		seen[id] = true
		out = append(out, id)
	}
	return out
}

// BuildInListOrBranch builds one AND-branch per de-duplicated list ID, all
// OR'd together. FilterOptimizer never combines IN_LIST branches, so this
// shape survives HubSpotListClient.CreateList's optimization pass unchanged.
func BuildInListOrBranch(listIDs []string) model.FilterBranch {
	branches := make([]model.FilterBranch, 0, len(listIDs))
	for _, id := range dedupeStrings(listIDs) {
		branches = append(branches, model.FilterBranch{
			FilterBranchType: "AND",
			FilterBranches:   []model.FilterBranch{},
			Filters: []model.Filter{
				{FilterType: "IN_LIST", ListID: id, Operator: "IN_LIST"},
			},
		})
	}
	return model.FilterBranch{FilterBranchType: "OR", FilterBranches: branches, Filters: []model.Filter{}}
}

var quarterCodeRe = regexp.MustCompile(`(\d{4})-(\d{2})-(\d{2})`)

// BuildMasterListName returns "<YYQN> - <Brand> - <Event> - <suffix>",
// falling back to today's quarter / a generic body when brand/event/dates
// aren't available.
func BuildMasterListName(eventURL, brandShort, eventName string, eventDates []string, suffix string) string {
	yyq := ""
	for _, ds := range eventDates {
		if m := quarterCodeRe.FindStringSubmatch(ds); m != nil {
			year, _ := strconv.Atoi(m[1])
			month, _ := strconv.Atoi(m[2])
			yyq = fmt.Sprintf("%02dQ%d", year%100, (month-1)/3+1)
			break
		}
	}
	if yyq == "" {
		now := currentQuarter()
		yyq = now
	}

	var parts []string
	for _, p := range []string{brandShort, eventName} {
		if p != "" {
			parts = append(parts, p)
		}
	}
	body := "Audience"
	if len(parts) > 0 {
		body = strings.Join(parts, " - ")
	}
	return fmt.Sprintf("%s - %s - %s", yyq, body, suffix)
}

// currentQuarter formats today's date as "YYQN". Extracted so tests can't be
// broken by running across a quarter boundary — callers that need a fixed
// date should pass event_dates instead.
func currentQuarter() string {
	now := time.Now()
	return fmt.Sprintf("%02dQ%d", now.Year()%100, (int(now.Month())-1)/3+1)
}

// StandardSuppressionTerm is one of the 6 portfolio-wide hygiene lists
// looked up by name search, matching the search terms in
// audience_tools.PLANNING_PROMPT_TEMPLATE STEP 5.
type StandardSuppressionTerm struct {
	Key   string
	Label string
	Term  string
}

var StandardSuppressionTerms = []StandardSuppressionTerm{
	{"lf_global_opt_outs", "LF Global Opt-Outs", "LF Global Opt-Outs"},
	{"lf_europe_global_opt_outs", "LF Europe Global Opt-Outs", "LF Europe Global Opt-Outs"},
	{"lf_events_gdpr", "LF Events GDPR Suppression", "LF Events GDPR Suppression"},
	{"lf_europe_gdpr", "LF Europe GDPR Suppression", "LF Europe GDPR Suppression"},
	{"lf_master_exclusion", "LF Master Exclusion List", "LF Master Exclusion"},
	{"lf_events_suppression", "LF Events Suppression List", "LF Events Suppression List"},
}

var quarterRankRe = regexp.MustCompile(`(?i)(\d{2})Q([1-4])`)

// quarterRank extracts a "YYQN" code from a list name for recency ranking.
// Names with no quarter code rank lowest (-1,-1) but are still eligible if
// they're the only match for their category.
func quarterRank(name string) (int, int) {
	m := quarterRankRe.FindStringSubmatch(name)
	if m == nil {
		return -1, -1
	}
	yy, _ := strconv.Atoi(m[1])
	q, _ := strconv.Atoi(m[2])
	return yy, q
}

var wordRe = regexp.MustCompile(`[a-z0-9]+`)
var stopwords = map[string]bool{"the": true, "a": true, "an": true, "and": true, "of": true, "for": true, "in": true, "on": true, "to": true}

func eventKeywords(text string) map[string]bool {
	out := map[string]bool{}
	for _, w := range wordRe.FindAllString(strings.ToLower(text), -1) {
		if len(w) > 2 && !stopwords[w] {
			out[w] = true
		}
	}
	return out
}

func keywordsOverlap(a, b map[string]bool) bool {
	for w := range a {
		if b[w] {
			return true
		}
	}
	return false
}

// sizeRank returns size for tie-breaking (0 when unknown), mirroring
// Python's `r.get("size") or 0`.
func sizeRank(l model.ListInfo) int { return l.Size }

// bestByQuarterThenSize picks the candidate with the highest (quarterRank,
// size) tuple, matching Python's max(candidates, key=...).
func bestByQuarterThenSize(candidates []model.ListInfo) model.ListInfo {
	best := candidates[0]
	bestYY, bestQ := quarterRank(best.Name)
	for _, c := range candidates[1:] {
		yy, q := quarterRank(c.Name)
		if yy > bestYY || (yy == bestYY && q > bestQ) ||
			(yy == bestYY && q == bestQ && sizeRank(c) > sizeRank(best)) {
			best, bestYY, bestQ = c, yy, q
		}
	}
	return best
}

func optionalSize(size int) *int {
	if size == 0 {
		return nil
	}
	v := size
	return &v
}

// findBrandOptOut looks up a brand-scoped "Global Opt Out" list, distinct
// from the 6 portfolio-wide STANDARD_SUPPRESSION_TERMS (confirmed against
// live HubSpot data: CNCF/Hyperledger/OpenSSF/Pytorch/LFN each have their
// own).
func (s *MasterListService) findBrandOptOut(ctx context.Context, brandShort string) *model.SuppressionList {
	if brandShort == "" {
		return nil
	}
	results, err := s.lists.SearchLists(ctx, brandShort+" Global Opt", 20)
	if err != nil {
		return nil
	}
	var candidates []model.ListInfo
	lower := strings.ToLower(brandShort)
	for _, r := range results {
		name := strings.ToLower(r.Name)
		if r.ID != "" && strings.Contains(name, lower) && strings.Contains(name, "opt") {
			candidates = append(candidates, r)
		}
	}
	if len(candidates) == 0 {
		return nil
	}
	best := bestByQuarterThenSize(candidates)
	return &model.SuppressionList{
		Key:      "brand_opt_out_" + lower,
		Label:    brandShort + " Global Opt-Out",
		ListID:   best.ID,
		Name:     best.Name,
		Size:     optionalSize(best.Size),
		Category: "brand",
	}
}

// findEventSuppression looks up a pre-existing per-event suppression list
// carried over from a prior edition.
func (s *MasterListService) findEventSuppression(ctx context.Context, eventName string) *model.SuppressionList {
	kw := eventKeywords(eventName)
	if len(kw) == 0 {
		return nil
	}
	byID := map[string]model.ListInfo{}
	for _, probe := range []string{eventName + " Suppression", eventName + " Exclusion"} {
		results, err := s.lists.SearchLists(ctx, probe, 20)
		if err != nil {
			continue
		}
		for _, r := range results {
			name := r.Name
			if r.ID == "" || !keywordsOverlap(kw, eventKeywords(name)) {
				continue
			}
			lower := strings.ToLower(name)
			if !strings.Contains(lower, "suppress") && !strings.Contains(lower, "exclusion") {
				continue
			}
			byID[r.ID] = r
		}
	}
	if len(byID) == 0 {
		return nil
	}
	candidates := make([]model.ListInfo, 0, len(byID))
	for _, v := range byID {
		candidates = append(candidates, v)
	}
	best := bestByQuarterThenSize(candidates)
	return &model.SuppressionList{
		Key:      "event_suppression",
		Label:    "Existing suppression for this event",
		ListID:   best.ID,
		Name:     best.Name,
		Size:     optionalSize(best.Size),
		Category: "event_specific",
	}
}

// FindStandardSuppressionLists deterministically resolves the standard
// hygiene suppression lists by name search, picking the most recently
// updated match per category, plus (when given) a brand-scoped opt-out list
// and an event-specific suppression list.
func (s *MasterListService) FindStandardSuppressionLists(ctx context.Context, brandShort, eventName string) []model.SuppressionList {
	var found []model.SuppressionList
	for _, term := range StandardSuppressionTerms {
		results, err := s.lists.SearchLists(ctx, term.Term, 20)
		if err != nil {
			continue
		}
		var candidates []model.ListInfo
		lowerTerm := strings.ToLower(term.Term)
		for _, r := range results {
			if r.ID != "" && strings.Contains(strings.ToLower(r.Name), lowerTerm) {
				candidates = append(candidates, r)
			}
		}
		if len(candidates) == 0 {
			continue
		}
		best := bestByQuarterThenSize(candidates)
		name := best.Name
		if name == "" {
			name = term.Label
		}
		found = append(found, model.SuppressionList{
			Key:      term.Key,
			Label:    term.Label,
			ListID:   best.ID,
			Name:     name,
			Size:     optionalSize(best.Size),
			Category: "standard",
		})
	}

	if brand := s.findBrandOptOut(ctx, brandShort); brand != nil {
		found = append(found, *brand)
	}
	if event := s.findEventSuppression(ctx, eventName); event != nil {
		found = append(found, *event)
	}
	return found
}

// FindExistingMasterLists finds master lists already built for this event by
// an earlier Audience Builder run, returning EVERY match (distinct past
// editions can legitimately coexist) sorted most-recent-quarter first.
func (s *MasterListService) FindExistingMasterLists(ctx context.Context, brandShort, eventName string) []model.ExistingMasterList {
	kw := eventKeywords(eventName)
	for w := range eventKeywords(brandShort) {
		kw[w] = true
	}
	if len(kw) == 0 {
		return []model.ExistingMasterList{}
	}

	byID := map[string]model.ListInfo{}
	probes := []string{strings.TrimSpace(eventName + " Master"), strings.TrimSpace(brandShort + " " + eventName + " Master")}
	for _, probe := range probes {
		if probe == "" {
			continue
		}
		results, err := s.lists.SearchLists(ctx, probe, 20)
		if err != nil {
			continue
		}
		for _, r := range results {
			if r.ID == "" || !strings.Contains(strings.ToLower(r.Name), "master") {
				continue
			}
			if !keywordsOverlap(kw, eventKeywords(r.Name)) {
				continue
			}
			byID[r.ID] = r
		}
	}

	ranked := make([]model.ListInfo, 0, len(byID))
	for _, v := range byID {
		ranked = append(ranked, v)
	}
	sort.Slice(ranked, func(i, j int) bool {
		yi, qi := quarterRank(ranked[i].Name)
		yj, qj := quarterRank(ranked[j].Name)
		if yi != yj {
			return yi > yj
		}
		return qi > qj
	})

	out := make([]model.ExistingMasterList, 0, len(ranked))
	for _, r := range ranked {
		out = append(out, model.ExistingMasterList{
			ListID:     r.ID,
			Name:       r.Name,
			Size:       optionalSize(r.Size),
			HubSpotURL: fmt.Sprintf("https://app.hubspot.com/contacts/%s/objectLists/%s/filters", s.portalID, r.ID),
		})
	}
	return out
}

func (s *MasterListService) listSize(ctx context.Context, listID string) int {
	info, err := s.lists.GetList(ctx, listID)
	if err != nil {
		return 0
	}
	return info.Size
}

// UnionSize returns the de-duplicated contact count across multiple lists,
// paginating each list's membership IDs and unioning client-side (capped at
// `cap` combined estimated contacts). Above the cap, or on any lookup
// failure, falls back to a naive sum-of-sizes estimate.
func (s *MasterListService) UnionSize(ctx context.Context, listIDs []string, cap int) model.PreviewCountResponse {
	if cap <= 0 {
		cap = 25000
	}
	ids := dedupeStrings(listIDs)
	if len(ids) == 0 {
		return model.PreviewCountResponse{}
	}

	estimate := 0
	for _, id := range ids {
		estimate += s.listSize(ctx, id)
	}
	if estimate > cap {
		return model.PreviewCountResponse{
			Exact:    false,
			Estimate: estimate,
			Count:    estimate,
			Reason:   fmt.Sprintf("combined size ~%d exceeds live-count limit (%d); showing sum estimate", estimate, cap),
		}
	}

	union := map[string]bool{}
	for _, id := range ids {
		memberIDs, err := s.lists.ListMembershipIDs(ctx, id, 0)
		if err != nil {
			return model.PreviewCountResponse{
				Exact:    false,
				Estimate: estimate,
				Count:    estimate,
				Reason:   "live membership lookup failed; showing sum estimate",
			}
		}
		for _, mid := range memberIDs {
			union[mid] = true
		}
	}
	return model.PreviewCountResponse{Exact: true, Estimate: estimate, Count: len(union)}
}

// BuildMasterFilterBranch builds one AND-branch per de-duplicated inclusion
// list ID, each ANDed with a NOT_IN_LIST filter on the single combined
// suppression list (if given), all OR'd together:
// (inc_1 AND NOT supp) OR (inc_2 AND NOT supp) ...
func BuildMasterFilterBranch(includeIDs []string, suppressionListID string) model.FilterBranch {
	ids := dedupeStrings(includeIDs)
	branches := make([]model.FilterBranch, 0, len(ids))
	for _, id := range ids {
		filters := []model.Filter{{FilterType: "IN_LIST", ListID: id, Operator: "IN_LIST"}}
		if suppressionListID != "" {
			filters = append(filters, model.Filter{FilterType: "IN_LIST", ListID: suppressionListID, Operator: "NOT_IN_LIST"})
		}
		branches = append(branches, model.FilterBranch{FilterBranchType: "AND", FilterBranches: []model.FilterBranch{}, Filters: filters})
	}
	return model.FilterBranch{FilterBranchType: "OR", FilterBranches: branches, Filters: []model.Filter{}}
}

// createWithRetry calls CreateList, appending a timestamp to the name and
// retrying once if a list with that exact name already exists (HubSpot
// returns a 400/409 whose body mentions "already exist").
func (s *MasterListService) createWithRetry(ctx context.Context, resolvedName string, filterBranch model.FilterBranch) (*model.CreatedList, string, error) {
	created, err := s.lists.CreateList(ctx, resolvedName, filterBranch)
	if err == nil {
		return created, resolvedName, nil
	}
	if !strings.Contains(strings.ToLower(err.Error()), "already exist") {
		return nil, "", err
	}
	resolvedName = fmt.Sprintf("%s (%s)", resolvedName, time.Now().Format("2006-01-02 15:04"))
	created, err = s.lists.CreateList(ctx, resolvedName, filterBranch)
	if err != nil {
		return nil, "", err
	}
	return created, resolvedName, nil
}

func sizeOrUnknown(size int, hadSize bool) string {
	if !hadSize {
		return "unknown"
	}
	return strconv.Itoa(size)
}

// ComposeMasterListFromIDs builds the master list from a set of
// already-discovered/selected HubSpot list IDs. If a list with the resolved
// name already exists, a new list is created with a timestamp appended
// rather than overwriting whichever list currently holds that name.
//
// If excludeListIDs is given, first builds a single "Combined Suppression"
// list (OR of IN_LIST over those IDs), then applies that one combined list
// as a NOT_IN_LIST exclusion inside every inclusion AND-branch — one shared
// exclusion, never the individual suppression lists repeated per branch.
func (s *MasterListService) ComposeMasterListFromIDs(
	ctx context.Context,
	listIDs []string,
	name, eventURL, brandShort, eventName string,
	eventDates []string,
	excludeListIDs []string,
) (*model.ComposeMasterListResponse, error) {
	if len(listIDs) == 0 {
		return nil, fmt.Errorf("list_ids must not be empty: %w", domain.ErrInvalidInput)
	}
	excludeIDs := dedupeStrings(excludeListIDs)

	response := &model.ComposeMasterListResponse{SourceListIDs: listIDs}

	suppressionListID := ""
	if len(excludeIDs) > 0 {
		suppName := strings.TrimSpace(name) + " - Combined Suppression"
		if strings.TrimSpace(name) == "" {
			suppName = BuildMasterListName(eventURL, brandShort, eventName, eventDates, "Combined Suppression")
		}
		suppResult, resolvedSuppName, err := s.createWithRetry(ctx, suppName, BuildInListOrBranch(excludeIDs))
		if err != nil {
			return nil, fmt.Errorf("create combined suppression list: %w", err)
		}
		suppressionListID = suppResult.ListID
		response.SuppressionListID = suppResult.ListID
		suppNameOut := suppResult.Name
		if suppNameOut == "" {
			suppNameOut = resolvedSuppName
		}
		response.SuppressionName = suppNameOut
		response.SuppressionHubSpotURL = suppResult.HubSpotURL
		response.SuppressionSize = sizeOrUnknown(suppResult.Size, suppResult.Size != 0)
	}

	resolvedName := strings.TrimSpace(name)
	if resolvedName == "" {
		resolvedName = BuildMasterListName(eventURL, brandShort, eventName, eventDates, "Master")
	}
	filterBranch := BuildMasterFilterBranch(listIDs, suppressionListID)

	result, resolvedName, err := s.createWithRetry(ctx, resolvedName, filterBranch)
	if err != nil {
		return nil, fmt.Errorf("create master list: %w", err)
	}

	response.ListID = result.ListID
	name2 := result.Name
	if name2 == "" {
		name2 = resolvedName
	}
	response.Name = name2
	response.HubSpotURL = result.HubSpotURL
	response.Size = sizeOrUnknown(result.Size, result.Size != 0)
	return response, nil
}
