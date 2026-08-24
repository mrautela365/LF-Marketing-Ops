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

// HubSpotEmailClient is the consolidated port for marketing-email
// operations, replacing the 3 independent Python clients
// (integrations/hubspot.py, audience_tools.py, hubspot_ab_workflow's
// hubspot_integration.py). Widget-level content read/write, image upload,
// and staged-email validation are intentionally deferred to the phase that
// ports core/agent.py's content-generation flow (they depend on that
// flow's HTML/section model, not on anything audience_builder needs).
type HubSpotEmailClient interface {
	GetEmailDetails(ctx context.Context, emailID string) (*model.EmailDetails, error)
	SearchEmails(ctx context.Context, opts EmailSearchOptions) ([]model.EmailSummary, error)
	CloneEmail(ctx context.Context, sourceEmailID, cloneName string) (*model.ClonedEmail, error)
	CreateABVariation(ctx context.Context, emailID, variationName string) (*model.EmailSummary, error)
	UpdateEmailSettings(ctx context.Context, emailID string, update EmailSettingsUpdate) error
	SetEmailSendList(ctx context.Context, emailID string, update SendListUpdate) error
	GetCampaign(ctx context.Context, emailID string) (campaignGUID, campaignName string, err error)
	GetCampaignUTM(ctx context.Context, campaignGUID string) (*model.CampaignUTM, error)
}

// HubSpotListClient is the consolidated port for contact-list operations.
// It intentionally does NOT reproduce hubspot_ab_workflow's
// search_lists_by_name/get_list_details — those hit endpoint shapes
// (/crm/v3/objects/lists...) that diverge from the two consistent, correct
// implementations and appear to target nonexistent HubSpot endpoints.
type HubSpotListClient interface {
	SearchLists(ctx context.Context, query string, limit int) ([]model.ListInfo, error)
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
