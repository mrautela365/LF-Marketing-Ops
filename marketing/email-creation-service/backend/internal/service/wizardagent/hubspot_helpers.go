package wizardagent

import (
	"context"
	"fmt"
	"sort"
	"strings"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
)

// allowedToolsList renders the tool names accepted by dispatchTool, for the
// "Unknown tool" error message — ports the f"Allowed: {...}" suffix of
// _execute_tool's else branch.
func allowedToolsList() string {
	names := make([]string, 0, len(Tools))
	for _, t := range Tools {
		names = append(names, t.Name)
	}
	sort.Strings(names)
	return strings.Join(names, ", ")
}

// lookupBrandHistory ports integrations/hubspot.py's lookup_brand_history.
//
// Python fetches up to 30 PUBLISHED emails matching the brand name (then
// client-side re-filters case-insensitively even though the API call
// already applied a name__icontains filter), computes settings_source as
// the single most recent match, and defaults clone_source to
// settings_source — but overrides clone_source to the most-recent email
// whose NAME contains email_type_hint, when a hint is given and one
// matches. Despite the settings_source/clone_source naming split, EVERY
// field in the returned dict is read off clone_source (Python aliases it
// `latest`) — settings_source itself is never actually read from once
// clone_source is picked.
//
// from_name/from_address fall back from the chosen email's "from" object to
// its "settings" object when both from-fields are empty. model.EmailSummary
// (unlike model.EmailDetails) carries no "settings" object — HubSpot's
// list-search response used by SearchEmails doesn't inline it — so this Go
// port issues one extra GetEmailDetails call in that (empty-from) case and
// uses EmailDetails.ResolvedFrom(), which implements the identical
// from-then-settings precedence. This is a documented, functionally
// equivalent substitute for Python's single-call inline read, at the cost
// of an extra HubSpot API call only when the primary search result's from
// fields are both empty.
//
// suppression_list_ids / send_list_ids (the included-list side) are the
// set-union of the chosen email's to.contactIlsLists and to.contactLists
// exclude/include arrays respectively — model.EmailSummary.To IS populated
// with these directly from HubSpot's inline list-search response (verified
// against dispatch/hubspot.go's SearchEmails, which decodes straight into
// []model.EmailSummary with no field-dropping), so no extra call is needed
// for this part, unlike an earlier revision of this function which
// incorrectly claimed suppression IDs were always empty.
func (a *Agent) lookupBrandHistory(ctx context.Context, brandName, emailTypeHint string) (map[string]any, error) {
	emails, err := a.Emails.SearchEmails(ctx, domain.EmailSearchOptions{
		NameContains:  brandName,
		Limit:         30,
		OrderBy:       "-publishDate",
		PublishedOnly: true,
	})
	if err != nil {
		return nil, err
	}

	lowerBrand := strings.ToLower(brandName)
	var matches []model.EmailSummary
	for _, e := range emails {
		if strings.Contains(strings.ToLower(e.Name), lowerBrand) {
			matches = append(matches, e)
		}
	}
	if len(matches) == 0 {
		return map[string]any{"found": false, "message": "No prior email found for brand " + brandName}, nil
	}

	// settings_source: the single most recent matching email. SearchEmails
	// is called with OrderBy "-publishDate", so matches[0] is already it.
	settingsSource := matches[0]

	// clone_source defaults to settings_source, but is overridden to the
	// most-recent email whose name contains email_type_hint (case
	// insensitive), when a hint is supplied and one of the brand's emails
	// matches it.
	cloneSource := settingsSource
	if emailTypeHint != "" {
		hint := strings.ToLower(emailTypeHint)
		for _, e := range matches {
			if strings.Contains(strings.ToLower(e.Name), hint) {
				cloneSource = e
				break
			}
		}
	}

	// Python aliases clone_source as `latest` — every returned field below
	// reads off it, never off settingsSource.
	latest := cloneSource

	fromName := latest.From.FromName
	fromAddress := latest.From.ReplyTo
	if fromName == "" && fromAddress == "" {
		if details, derr := a.Emails.GetEmailDetails(ctx, latest.ID); derr == nil && details != nil {
			resolved := details.ResolvedFrom()
			fromName = resolved.FromName
			fromAddress = resolved.ReplyTo
		}
	}

	suppressionListIDs := unionStrings(latest.To.ContactIlsLists.Exclude, latest.To.ContactLists.Exclude)
	sendListIDs := unionStrings(latest.To.ContactIlsLists.Include, latest.To.ContactLists.Include)

	return map[string]any{
		"found":                true,
		"last_email_id":        latest.ID,
		"last_email_name":      latest.Name,
		"from_name":            fromName,
		"from_address":         fromAddress,
		"email_type":           latest.Type,
		"suppression_list_ids": suppressionListIDs,
		"send_list_ids":        sendListIDs,
		"subscription_type_id": latest.To.SubscriptionID,
	}, nil
}

// unionStrings returns the deduplicated, order-preserving union of a and b,
// dropping empty strings — used to combine contactIlsLists/contactLists
// include or exclude arrays into a single logical list-ID set, matching
// Python's set-union of the two namespaces.
func unionStrings(a, b []string) []string {
	seen := make(map[string]bool, len(a)+len(b))
	var out []string
	for _, s := range a {
		if s == "" || seen[s] {
			continue
		}
		seen[s] = true
		out = append(out, s)
	}
	for _, s := range b {
		if s == "" || seen[s] {
			continue
		}
		seen[s] = true
		out = append(out, s)
	}
	return out
}

// setEmailSendList ports integrations/hubspot.py's set_email_send_list — a
// convenience wrapper with no direct Go equivalent (only the lower-level
// HubSpotEmailClient.SetEmailSendList primitive exists).
//
// Python raises ValueError immediately — a hard reject, listing the
// conflicting IDs — if a single call's send_list_ids resolve to BOTH the
// ILS and legacy namespaces; it never silently merges or picks one. This Go
// port now matches that: each ID is classified via HubSpotListClient.
// IsILSList, and if the resulting sets are non-empty on both sides, the
// call is rejected before any PATCH is attempted, instead of the earlier
// revision's behavior of silently building a mixed-namespace
// domain.SendListUpdate (which also violates that struct's own documented
// "exactly one of ContactLists / ContactIlsLists" contract).
//
// Suppression IDs are routed to the SAME namespace as the (single,
// now-guaranteed-unmixed) send list only — Python never explicitly adds a
// suppression to the opposite namespace, relying on HubSpot's automatic
// exclude-mirroring across namespaces for a single list.
//
// Python's PATCH also explicitly clears contactIds: {"include": [],
// "exclude": []} on every call, to strip stale individually-added contacts
// left over from the clone source — dispatch.HubSpotClient.SetEmailSendList
// now always includes that clear in its "to" payload unconditionally, so
// this behavior is reproduced at the dispatch layer rather than here.
// SetSendListResult carries set_email_send_list's return dict fields that
// Python never discards: the actual processingType of the (now-guaranteed-
// unmixed) send list namespace, whether every requested list ID actually
// landed in HubSpot's PATCH response, and the applied "to" object itself.
type SetSendListResult struct {
	Success  bool
	ListType string
	To       model.EmailRecipients
}

func (a *Agent) setEmailSendList(ctx context.Context, emailID string, sendListIDs, suppressionListIDs []string) (SetSendListResult, error) {
	if len(sendListIDs) == 0 {
		return SetSendListResult{}, nil
	}

	var ilsInclude, legacyInclude []string
	for _, id := range sendListIDs {
		isILS, err := a.Lists.IsILSList(ctx, id)
		if err != nil {
			return SetSendListResult{}, err
		}
		if isILS {
			ilsInclude = append(ilsInclude, id)
		} else {
			legacyInclude = append(legacyInclude, id)
		}
	}

	if len(ilsInclude) > 0 && len(legacyInclude) > 0 {
		return SetSendListResult{}, fmt.Errorf(
			"setEmailSendList: send_list_ids resolve to both ILS and legacy list namespaces "+
				"(ILS: %s; legacy: %s) — HubSpot rejects a single PATCH mixing both namespaces; "+
				"split into separate calls per namespace",
			strings.Join(ilsInclude, ", "), strings.Join(legacyInclude, ", "))
	}

	// list_type mirrors Python's list_types[send_list_ids[0]] — the actual
	// HubSpot processingType of the first requested list ("UNKNOWN" for a
	// legacy list not found in CRM v3), not just "ils"/"legacy".
	listType, err := a.Lists.GetListProcessingType(ctx, sendListIDs[0])
	if err != nil {
		return SetSendListResult{}, err
	}

	// Route suppression IDs to match the send list's (now-guaranteed-single)
	// namespace: ILS-namespace send lists get ILS-namespace suppressions,
	// legacy send lists get legacy suppressions.
	var ilsExclude, legacyExclude []string
	if len(ilsInclude) > 0 {
		for _, id := range suppressionListIDs {
			isILS, err := a.Lists.IsILSList(ctx, id)
			if err != nil {
				continue
			}
			if isILS {
				ilsExclude = append(ilsExclude, id)
			}
		}
	} else {
		for _, id := range suppressionListIDs {
			isILS, err := a.Lists.IsILSList(ctx, id)
			if err != nil {
				continue
			}
			if !isILS {
				legacyExclude = append(legacyExclude, id)
			}
		}
	}

	update := domain.SendListUpdate{}
	if len(ilsInclude) > 0 {
		update.ContactIlsLists.Include = ilsInclude
		update.ContactIlsLists.Exclude = ilsExclude
	}
	if len(legacyInclude) > 0 {
		update.ContactLists.Include = legacyInclude
		update.ContactLists.Exclude = legacyExclude
	}

	appliedTo, err := a.Emails.SetEmailSendList(ctx, emailID, update)
	if err != nil {
		return SetSendListResult{}, err
	}

	// success mirrors Python's `all(sid in all_applied for sid in
	// send_list_ids)` — HubSpot silently drops a `to` update it rejects, so
	// the PATCH call succeeding is not itself proof the lists were applied.
	applied := make(map[string]bool, len(appliedTo.ContactLists.Include)+len(appliedTo.ContactIlsLists.Include))
	for _, id := range appliedTo.ContactLists.Include {
		applied[id] = true
	}
	for _, id := range appliedTo.ContactIlsLists.Include {
		applied[id] = true
	}
	success := true
	for _, id := range sendListIDs {
		if !applied[id] {
			success = false
			break
		}
	}

	return SetSendListResult{Success: success, ListType: listType, To: appliedTo}, nil
}
