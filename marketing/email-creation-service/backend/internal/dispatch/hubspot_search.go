package dispatch

import (
	"context"
	"fmt"
	"net/http"
	"net/url"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/eventbrands"
)

// fetchPublishedEmails runs a name__icontains search over
// /marketing/v3/emails, ordered newest-first, filtered to PUBLISHED state —
// the shared fetch shape behind search_emails_for_event and
// get_brand_emails's tiered searches.
func (c *HubSpotClient) fetchPublishedEmails(ctx context.Context, nameContains string, limit int) ([]model.EmailSummary, error) {
	q := url.Values{
		"limit":           {strconv.Itoa(limit)},
		"name__icontains": {nameContains},
		"orderBy":         {"-publishDate"},
	}
	var page struct {
		Results []model.EmailSummary `json:"results"`
	}
	if err := c.request(ctx, http.MethodGet, "/marketing/v3/emails", q, nil, &page); err != nil {
		return nil, err
	}
	out := make([]model.EmailSummary, 0, len(page.Results))
	for _, e := range page.Results {
		if e.State == "PUBLISHED" {
			out = append(out, e)
		}
	}
	return out, nil
}

func typeBonus(name, hint string) int {
	if hint == "" {
		return 0
	}
	if strings.Contains(strings.ToLower(name), hint) {
		return 1
	}
	return 0
}

func dedupeStrings(lists ...[]string) []string {
	seen := map[string]struct{}{}
	var out []string
	for _, l := range lists {
		for _, s := range l {
			if s == "" {
				continue
			}
			if _, ok := seen[s]; ok {
				continue
			}
			seen[s] = struct{}{}
			out = append(out, s)
		}
	}
	return out
}

// SearchEmailsForEvent ports search_emails_for_event.
func (c *HubSpotClient) SearchEmailsForEvent(ctx context.Context, opts domain.SearchEmailsForEventOptions) (*model.EventEmailMatch, error) {
	typeHint := strings.ToLower(strings.TrimSpace(opts.EmailType))

	tiers := []struct{ name, filter string }{
		{"event_name", opts.EventName},
		{"event_short_name", opts.EventShortName},
		{"short_brand_name", opts.ShortBrandName},
		{"brand_name", opts.BrandName},
	}

	var emails []model.EmailSummary
	matchedTier := ""
	for _, t := range tiers {
		if t.filter == "" {
			continue
		}
		fetched, err := c.fetchPublishedEmails(ctx, t.filter, 100)
		if err != nil {
			return nil, err
		}
		if len(fetched) > 0 {
			emails = fetched
			matchedTier = t.name
			break
		}
	}

	if len(emails) == 0 {
		return &model.EventEmailMatch{
			Found:   false,
			Message: fmt.Sprintf("No sent emails found for event '%s' / brand '%s'.", opts.EventName, opts.BrandName),
		}, nil
	}

	filtered, localeFilter := eventbrands.FilterCandidatesByLocale(emails, opts.EventName, opts.Location, func(e model.EmailSummary) string { return e.Name })
	if len(filtered) == 0 {
		loc := opts.Location
		if loc == "" {
			loc = "unknown"
		}
		return &model.EventEmailMatch{
			Found: false,
			Message: fmt.Sprintf(
				"Found past emails for '%s', but none for this event's location ('%s') — ask the user for from_name, from_address, subscription_type, and suppression_list_ids.",
				opts.BrandName, loc,
			),
		}, nil
	}

	sort.SliceStable(filtered, func(i, j int) bool {
		pi, pj := filtered[i].PublishDate, filtered[j].PublishDate
		if pi != pj {
			return pi > pj
		}
		return typeBonus(filtered[i].Name, typeHint) > typeBonus(filtered[j].Name, typeHint)
	})

	best := filtered[0]
	bestScore := typeBonus(best.Name, typeHint)

	suppressionIDs := dedupeStrings(best.To.ContactIlsLists.Exclude, best.To.ContactLists.Exclude)
	includedIDs := dedupeStrings(best.To.ContactIlsLists.Include, best.To.ContactLists.Include)

	return &model.EventEmailMatch{
		Found:              true,
		EventMatch:         matchedTier == "event_name" || matchedTier == "event_short_name",
		MatchedTier:        matchedTier,
		LocaleFilter:       localeFilter,
		MatchedEmailID:     best.ID,
		MatchedEmailName:   best.Name,
		MatchedScore:       bestScore,
		FromName:           best.From.FromName,
		FromAddress:        best.From.ReplyTo,
		EmailType:          orDefault(best.Type, "BATCH_EMAIL"),
		SuppressionListIDs: suppressionIDs,
		IncludedListIDs:    includedIDs,
	}, nil
}

func orDefault(s, def string) string {
	if s == "" {
		return def
	}
	return s
}

// slugGeneric are generic conference words stripped when building slug
// search tokens — brand-specific abbreviations (mcp, cfp, kcd, etc.) and
// locations are kept.
var slugGeneric = map[string]struct{}{
	"summit": {}, "conference": {}, "con": {}, "forum": {}, "day": {}, "days": {},
	"event": {}, "events": {}, "virtual": {}, "online": {}, "global": {},
	"north": {}, "south": {}, "east": {}, "west": {}, "central": {},
}

var anchorSkip = map[string]struct{}{
	"lf": {}, "the": {}, "a": {}, "an": {}, "of": {}, "for": {}, "and": {}, "or": {},
}

var slugSplitRe = regexp.MustCompile(`[-_]`)

// slugKeyTokens extracts meaningful search tokens from an event URL slug,
// e.g. mcp-dev-summit-toronto -> ["mcp", "dev", "toronto"].
func slugKeyTokens(rawURL string) []string {
	u, err := url.Parse(rawURL)
	if err != nil {
		return nil
	}
	path := strings.Trim(u.Path, "/")
	parts := strings.Split(path, "/")
	slug := parts[len(parts)-1]

	var tokens []string
	for _, t := range slugSplitRe.Split(slug, -1) {
		t = strings.ToLower(t)
		if len(t) <= 1 {
			continue
		}
		if _, skip := slugGeneric[t]; skip {
			continue
		}
		tokens = append(tokens, t)
	}
	return tokens
}

// GetBrandEmails ports get_brand_emails.
func (c *HubSpotClient) GetBrandEmails(ctx context.Context, opts domain.GetBrandEmailsOptions) ([]model.EmailSummary, error) {
	limitPerCall := opts.LimitPerCall
	if limitPerCall <= 0 {
		limitPerCall = 20
	}

	seen := map[string]struct{}{}
	var all []model.EmailSummary

	fetchAndAdd := func(filter string) error {
		filter = strings.TrimSpace(filter)
		if len(filter) < 2 {
			return nil
		}
		fetched, err := c.fetchPublishedEmails(ctx, filter, limitPerCall)
		if err != nil {
			return err
		}
		for _, e := range fetched {
			if e.ID == "" {
				continue
			}
			if _, ok := seen[e.ID]; ok {
				continue
			}
			seen[e.ID] = struct{}{}
			all = append(all, e)
		}
		return nil
	}

	fetchTokenized := func(anchor string, rest []string) error {
		anchor = strings.TrimSpace(anchor)
		if len(anchor) < 2 {
			return nil
		}
		fetched, err := c.fetchPublishedEmails(ctx, anchor, limitPerCall*3)
		if err != nil {
			return err
		}
		for _, e := range fetched {
			if e.ID == "" {
				continue
			}
			if _, ok := seen[e.ID]; ok {
				continue
			}
			nameLower := strings.ToLower(e.Name)
			match := true
			for _, r := range rest {
				if !strings.Contains(nameLower, strings.ToLower(r)) {
					match = false
					break
				}
			}
			if match {
				seen[e.ID] = struct{}{}
				all = append(all, e)
			}
		}
		return nil
	}

	// Tier 1 — brand short code, wrapped in " - " to match naming convention.
	if opts.ShortBrandName != "" {
		if err := fetchAndAdd(fmt.Sprintf("- %s -", opts.ShortBrandName)); err != nil {
			return nil, err
		}
		if err := fetchAndAdd(fmt.Sprintf("- %s ", opts.ShortBrandName)); err != nil {
			return nil, err
		}
	}

	// Tier 2 — event short names, smart anchor selection.
	for _, esn := range opts.EventShortNames {
		if esn == "" {
			continue
		}
		parts := strings.Fields(esn)
		if len(parts) == 1 {
			if err := fetchAndAdd(esn); err != nil {
				return nil, err
			}
			continue
		}
		anchorIdx := 0
		for i, p := range parts {
			if _, skip := anchorSkip[strings.ToLower(p)]; !skip && len(p) > 2 {
				anchorIdx = i
				break
			}
		}
		anchor := parts[anchorIdx]
		var rest []string
		for i, p := range parts {
			if i != anchorIdx {
				rest = append(rest, p)
			}
		}
		if err := fetchTokenized(anchor, rest); err != nil {
			return nil, err
		}
	}

	// Tier 3 — URL slug tokens.
	if opts.EventURL != "" {
		tokens := slugKeyTokens(opts.EventURL)
		switch {
		case len(tokens) >= 2:
			if err := fetchTokenized(tokens[0], tokens[1:]); err != nil {
				return nil, err
			}
		case len(tokens) == 1:
			if err := fetchAndAdd(tokens[0]); err != nil {
				return nil, err
			}
		}
	}

	// Tier 4 — full brand name fallback, only when results are still thin.
	if len(all) < 10 {
		if err := fetchAndAdd(opts.BrandName); err != nil {
			return nil, err
		}
	}

	sort.SliceStable(all, func(i, j int) bool { return all[i].PublishDate > all[j].PublishDate })
	if len(all) > 60 {
		all = all[:60]
	}
	return all, nil
}
