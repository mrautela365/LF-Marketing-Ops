package domain

import (
	"context"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
)

// EmailSearchOptions parameterizes HubSpotEmailClient.SearchEmails. This
// consolidates 4 near-duplicate Python search functions
// (lookup_brand_history, hubspot_search_emails_raw, search_emails_by_name,
// hubspot_search_campaigns) into one call shape; PublishedOnly reproduces
// the client-side state=="PUBLISHED" filter some callers applied.
type EmailSearchOptions struct {
	NameContains  string
	Limit         int
	OrderBy       string // e.g. "-publishDate", "-createdAt"; defaults to "-publishDate"
	PublishedOnly bool
}

// EmailSettingsUpdate parameterizes HubSpotEmailClient.UpdateEmailSettings.
// Zero-value fields are left untouched (matches the Python only-set-keys
// PATCH behavior); PreviewText requires a read-merge-write against the
// email's current content to avoid clobbering flexAreas/templatePath.
type EmailSettingsUpdate struct {
	Subject     *string
	Type        *string
	FromName    *string
	ReplyTo     *string
	PreviewText *string
}

// SendListUpdate parameterizes HubSpotEmailClient.SetEmailSendList. Exactly
// one of ContactLists / ContactIlsLists may be non-empty per call — HubSpot
// rejects a PATCH mixing both namespaces in the same "to" object. Use
// HubSpotListClient.IsILSList to decide which namespace a given list ID
// belongs to before building this.
type SendListUpdate struct {
	ContactLists    model.ListIncludeExclude
	ContactIlsLists model.ListIncludeExclude
}

// SearchEmailsForEventOptions parameterizes
// HubSpotEmailClient.SearchEmailsForEvent — ports search_emails_for_event's
// argument list.
type SearchEmailsForEventOptions struct {
	BrandName      string
	EventName      string
	Location       string
	ShortBrandName string
	EventShortName string
	EmailType      string
}

// GetBrandEmailsOptions parameterizes HubSpotEmailClient.GetBrandEmails —
// ports get_brand_emails's argument list. LimitPerCall defaults to 20.
type GetBrandEmailsOptions struct {
	ShortBrandName  string
	BrandName       string
	EventShortNames []string
	EventURL        string
	LimitPerCall    int
}

// UpdateEmailContentInput parameterizes HubSpotEmailClient.UpdateEmailContent
// — ports update_email_content's argument list.
type UpdateEmailContentInput struct {
	HTMLContent     string
	BannerURL       string
	EventURL        string
	ContentSections []model.ContentSection
	Sponsors        []model.ScrapedSponsor
	UTMParams       map[string]string
	SentByOrg       string
}

// HubSpotEmailClient is the consolidated port for marketing-email
// operations, replacing the 3 independent Python clients
// (integrations/hubspot.py, audience_tools.py, hubspot_ab_workflow's
// hubspot_integration.py).
type HubSpotEmailClient interface {
	GetEmailDetails(ctx context.Context, emailID string) (*model.EmailDetails, error)
	SearchEmails(ctx context.Context, opts EmailSearchOptions) ([]model.EmailSummary, error)
	CloneEmail(ctx context.Context, sourceEmailID, cloneName string) (*model.ClonedEmail, error)
	CreateABVariation(ctx context.Context, emailID, variationName string) (*model.EmailSummary, error)
	UpdateEmailSettings(ctx context.Context, emailID string, update EmailSettingsUpdate) error
	// SetEmailSendList returns the "to" object HubSpot actually stored after
	// the PATCH, so callers can verify every requested list ID landed and
	// report the applied namespace — matching Python's set_email_send_list
	// return dict, which is never discarded.
	SetEmailSendList(ctx context.Context, emailID string, update SendListUpdate) (model.EmailRecipients, error)
	GetCampaign(ctx context.Context, emailID string) (campaignGUID, campaignName string, err error)
	GetCampaignUTM(ctx context.Context, campaignGUID string) (*model.CampaignUTM, error)

	// ResolveUTMCampaign follows sourceEmailID to its HubSpot Campaign and
	// reads that campaign's hs_utm value, falling back to a slug built from
	// fallbackName. Never returns an error — ports resolve_utm_campaign's
	// never-raises contract.
	ResolveUTMCampaign(ctx context.Context, sourceEmailID, fallbackName string) (*model.UTMResolution, error)
	// SearchEmailsForEvent ports search_emails_for_event's 4-tier waterfall
	// search + locale filter + rank-by-recency.
	SearchEmailsForEvent(ctx context.Context, opts SearchEmailsForEventOptions) (*model.EventEmailMatch, error)
	// GetBrandEmails ports get_brand_emails's 4-tier fetch, deduplicated by
	// ID and capped at 60, newest-first.
	GetBrandEmails(ctx context.Context, opts GetBrandEmailsOptions) ([]model.EmailSummary, error)
	// GetEmailContentText ports get_email_content_text — reads the
	// structured widget/section content of an existing email.
	GetEmailContentText(ctx context.Context, emailID string) (*model.EmailContentText, error)
	// UpdateEmailContent ports update_email_content — the DnD content
	// writer that rebuilds an email's flexAreas/widgets.
	UpdateEmailContent(ctx context.Context, emailID string, input UpdateEmailContentInput) (*model.UpdateEmailContentResult, error)
	// ValidateStagedEmail ports validate_staged_email — re-fetches and
	// checks a staged email's content was actually saved.
	ValidateStagedEmail(ctx context.Context, emailID string, expectBanner bool, expectSections int) (*model.ValidateStagedEmailResult, error)
	// UploadImageToHubSpot ports upload_image_to_hubspot. Never returns an
	// error — returns "" on any download/upload failure, matching Python.
	UploadImageToHubSpot(ctx context.Context, imageURL, filename string) (string, error)
}

// HubSpotListClient is the consolidated port for contact-list operations.
// It intentionally does NOT reproduce hubspot_ab_workflow's
// search_lists_by_name/get_list_details — those hit endpoint shapes
// (/crm/v3/objects/lists...) that diverge from the two consistent, correct
// implementations and appear to target nonexistent HubSpot endpoints.
type HubSpotListClient interface {
	// SearchLists ports audience_tools.py's hubspot_search_lists (count
	// hardcoded to 20, no processingTypes filter, keeps entries even when
	// name/id are missing) — used by the audience-builder services.
	SearchLists(ctx context.Context, query string, limit int) ([]model.ListInfo, error)
	// SearchListsByName ports integrations/hubspot.py's search_lists — a
	// distinct function with its own behavior (query<2 chars short-circuits
	// to empty, limit defaults to 10, filters to
	// MANUAL/SNAPSHOT/DYNAMIC processingTypes, drops entries missing a
	// name or id, and reads size only from additionalProperties.hs_list_size)
	// — used by the /api/lists/search route and the wizard agent's
	// search_hubspot_lists tool (via search_hubspot_lists's thin wrapper).
	SearchListsByName(ctx context.Context, query string, limit int) ([]model.ListInfo, error)
	GetList(ctx context.Context, listID string) (*model.ListInfo, error)
	// GetListProcessingType returns the list's HubSpot processingType
	// (MANUAL/SNAPSHOT/DYNAMIC), or "UNKNOWN" if the list isn't found in
	// CRM v3 (i.e. it's a legacy list).
	GetListProcessingType(ctx context.Context, listID string) (string, error)
	// IsILSList reports whether listID routes through CRM v3 "ILS"
	// (contactIlsLists) rather than the legacy contactLists namespace —
	// true for any processingType in {DYNAMIC, MANUAL, SNAPSHOT}.
	IsILSList(ctx context.Context, listID string) (bool, error)
	// ListMembershipIDs paginates GET .../memberships up to capPages pages
	// of 250 (matches the Python cap of ~25,000 records at capPages=100).
	ListMembershipIDs(ctx context.Context, listID string, capPages int) ([]string, error)
	CreateList(ctx context.Context, name string, filterBranch model.FilterBranch) (*model.CreatedList, error)
	UpdateListFilters(ctx context.Context, listID string, filterBranch model.FilterBranch) error
	GetEventTypes(ctx context.Context) ([]model.EventTypeDef, error)
	// GetLegacyListName looks up a legacy (v1) contact list's name, for IDs
	// that don't resolve via CRM v3 (see GetListProcessingType). exists is
	// false on a 404 or a HubSpot-reported "deleted" list.
	GetLegacyListName(ctx context.Context, listID string) (name string, exists bool, err error)
}
