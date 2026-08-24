package audience

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strings"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
)

// LastSentService finds previously-sent marketing emails for an event and
// resolves their include/exclude list IDs to display info — ported from
// audience_builder/last_sent.py.
type LastSentService struct {
	emails   domain.HubSpotEmailClient
	lists    domain.HubSpotListClient
	portalID string
}

func NewLastSentService(emails domain.HubSpotEmailClient, lists domain.HubSpotListClient, portalID string) *LastSentService {
	return &LastSentService{emails: emails, lists: lists, portalID: portalID}
}

var yearRe = regexp.MustCompile(`\b(19|20)\d{2}\b`)
var whitespaceRe = regexp.MustCompile(`\s+`)

// stripYear drops a trailing/embedded 4-digit year, e.g. "MCP Dev Summit
// Seoul 2026" -> "MCP Dev Summit Seoul". The discovery agent often appends
// the event's year to event_name, which breaks HubSpot's name__icontains
// search since most email names for an event don't repeat the year
// literally.
func stripYear(text string) string {
	stripped := yearRe.ReplaceAllString(text, "")
	return strings.TrimSpace(whitespaceRe.ReplaceAllString(stripped, " "))
}

// resolveListBrief resolves a list ID referenced on a past send to
// {list_id, name, size}. The email's to.contactLists/contactIlsLists fields
// freeze whatever list ID was attached at send time; when that ID 404s on
// v3 it usually isn't gone — it's the old (v1) numbering for a list HubSpot
// has since carried forward under a new v3 listId. We recover the live v3
// list via the legacy v1 endpoint (for the name) + a v3 name search (for the
// current ID/size), and only fall back to missing=true if that recovery
// fails too, i.e. the list is actually gone, not just renumbered.
func (s *LastSentService) resolveListBrief(ctx context.Context, listID string, cache map[string]model.ListBrief) model.ListBrief {
	if b, ok := cache[listID]; ok {
		return b
	}

	info, err := s.lists.GetList(ctx, listID)
	if err == nil {
		name := info.Name
		if name == "" {
			name = listID
		}
		brief := model.ListBrief{ListID: listID, Name: name, Size: optionalSize(info.Size)}
		cache[listID] = brief
		return brief
	}
	if !isNotFoundErr(err) {
		brief := model.ListBrief{ListID: listID, Name: fmt.Sprintf("List %s (lookup failed)", listID), Missing: true}
		cache[listID] = brief
		return brief
	}

	legacyName, exists, legacyErr := s.lists.GetLegacyListName(ctx, listID)
	if legacyErr == nil && exists && legacyName != "" {
		if results, searchErr := s.lists.SearchLists(ctx, legacyName, 20); searchErr == nil {
			for _, r := range results {
				if r.Name == legacyName && r.ID != "" {
					brief := model.ListBrief{ListID: r.ID, Name: r.Name, Size: optionalSize(r.Size), ResolvedFromLegacyID: listID}
					cache[listID] = brief
					return brief
				}
			}
		}
		brief := model.ListBrief{
			ListID:  listID,
			Name:    fmt.Sprintf("%q (renumbered in HubSpot; original ID %s could not be re-matched)", legacyName, listID),
			Missing: true,
		}
		cache[listID] = brief
		return brief
	}

	brief := model.ListBrief{ListID: listID, Name: fmt.Sprintf("List %s (no longer exists in HubSpot)", listID), Missing: true}
	cache[listID] = brief
	return brief
}

func isNotFoundErr(err error) bool {
	return err != nil && errors.Is(err, domain.ErrNotFound)
}

// dedupeBriefs collapses briefs referencing the same resolved list_id — a
// raw ID list can contain both a legacy v1 ID and its live v3 ID for the
// same list (e.g. static + dynamic recipient fields both referencing it),
// and resolveListBrief resolves the legacy one to the same v3 list_id.
func dedupeBriefs(briefs []model.ListBrief) []model.ListBrief {
	seen := map[string]bool{}
	out := make([]model.ListBrief, 0, len(briefs))
	for _, b := range briefs {
		if seen[b.ListID] {
			continue
		}
		seen[b.ListID] = true
		out = append(out, b)
	}
	return out
}

type scoredEmail struct {
	score int
	email model.EmailSummary
}

// FindLastSentEmails returns up to `limit` most-recently-published
// marketing emails whose name references this event, sorted by publishDate
// desc, with each email's included/suppression list IDs resolved to
// {list_id, name, size}.
//
// Searches by event_name first (server-side name__icontains), falling back
// to brand_short if that comes back with no published email — event names
// are often abbreviated differently across editions, so results are
// additionally ranked by keyword overlap rather than trusted on substring
// match alone.
func (s *LastSentService) FindLastSentEmails(ctx context.Context, eventName, brandShort string, limit int) ([]model.LastSentEmail, error) {
	if limit <= 0 {
		limit = 3
	}
	term := strings.TrimSpace(eventName)
	if term == "" {
		term = strings.TrimSpace(brandShort)
	}
	if term == "" {
		return []model.LastSentEmail{}, nil
	}

	searchTerm := stripYear(term)
	if searchTerm == "" {
		searchTerm = term
	}

	published, err := s.searchPublished(ctx, searchTerm)
	if err != nil {
		return nil, err
	}

	if len(published) == 0 && brandShort != "" && !strings.EqualFold(strings.TrimSpace(brandShort), searchTerm) {
		published, err = s.searchPublished(ctx, strings.TrimSpace(brandShort))
		if err != nil {
			return nil, err
		}
	}

	queryKw := eventKeywords(eventName)
	for w := range eventKeywords(brandShort) {
		queryKw[w] = true
	}

	scored := make([]scoredEmail, 0, len(published))
	for _, e := range published {
		score := 0
		if len(queryKw) > 0 {
			nameKw := eventKeywords(e.Name)
			for w := range queryKw {
				if nameKw[w] {
					score++
				}
			}
		}
		scored = append(scored, scoredEmail{score: score, email: e})
	}
	if len(queryKw) > 0 {
		matched := make([]scoredEmail, 0, len(scored))
		for _, p := range scored {
			if p.score > 0 {
				matched = append(matched, p)
			}
		}
		if len(matched) > 0 {
			scored = matched
		}
	}
	// published is already sorted -publishDate server-side; a stable sort
	// on keyword score alone preserves that as the tiebreak.
	sort.SliceStable(scored, func(i, j int) bool { return scored[i].score > scored[j].score })

	if len(scored) > limit {
		scored = scored[:limit]
	}

	cache := map[string]model.ListBrief{}
	results := make([]model.LastSentEmail, 0, len(scored))
	for _, p := range scored {
		e := p.email
		includedIDs := append(append([]string{}, e.To.ContactLists.Include...), e.To.ContactIlsLists.Include...)
		excludedIDs := append(append([]string{}, e.To.ContactLists.Exclude...), e.To.ContactIlsLists.Exclude...)

		includedBriefs := make([]model.ListBrief, 0, len(includedIDs))
		for _, id := range includedIDs {
			includedBriefs = append(includedBriefs, s.resolveListBrief(ctx, id, cache))
		}
		excludedBriefs := make([]model.ListBrief, 0, len(excludedIDs))
		for _, id := range excludedIDs {
			excludedBriefs = append(excludedBriefs, s.resolveListBrief(ctx, id, cache))
		}

		sentAt := e.PublishDate
		if sentAt == "" {
			sentAt = e.UpdatedAt
		}
		hubspotURL := ""
		if e.ID != "" {
			hubspotURL = fmt.Sprintf("https://app.hubspot.com/email/%s/edit/%s", s.portalID, e.ID)
		}

		results = append(results, model.LastSentEmail{
			EmailID:          e.ID,
			EmailName:        e.Name,
			SentAt:           sentAt,
			HubSpotURL:       hubspotURL,
			IncludedLists:    dedupeBriefs(includedBriefs),
			SuppressionLists: dedupeBriefs(excludedBriefs),
		})
	}
	return results, nil
}

func (s *LastSentService) searchPublished(ctx context.Context, term string) ([]model.EmailSummary, error) {
	all, err := s.emails.SearchEmails(ctx, domain.EmailSearchOptions{NameContains: term, Limit: 30, OrderBy: "-publishDate"})
	if err != nil {
		return nil, err
	}
	published := make([]model.EmailSummary, 0, len(all))
	for _, e := range all {
		if e.State == "PUBLISHED" {
			published = append(published, e)
		}
	}
	return published, nil
}
