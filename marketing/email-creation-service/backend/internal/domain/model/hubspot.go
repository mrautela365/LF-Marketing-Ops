// Package model holds framework-agnostic domain structs — no HTTP/JSON
// transport concerns beyond the json tags needed to talk to HubSpot's API,
// no ORM tags (there is no database in this service).
package model

// ListIncludeExclude mirrors HubSpot's {"include": [...], "exclude": [...]}
// shape used throughout the Marketing Emails "to" object.
type ListIncludeExclude struct {
	Include []string `json:"include,omitempty"`
	Exclude []string `json:"exclude,omitempty"`
}

// EmailFrom holds the from-name/reply-to pair that appears in both the
// email's top-level "from" and "settings" objects. When both are present,
// "from" wins (see HubSpotEmailClient.GetEmailDetails).
type EmailFrom struct {
	FromName string `json:"fromName,omitempty"`
	ReplyTo  string `json:"replyTo,omitempty"`
}

// EmailRecipients mirrors a marketing email's "to" object: legacy
// contactLists live alongside CRM v3 "ILS" contactIlsLists — never both
// populated for the same list ID (see SetEmailSendList quirks).
type EmailRecipients struct {
	ContactLists    ListIncludeExclude `json:"contactLists,omitempty"`
	ContactIlsLists ListIncludeExclude `json:"contactIlsLists,omitempty"`
	ContactIDs      ListIncludeExclude `json:"contactIds,omitempty"`
	SubscriptionID  string             `json:"subscriptionId,omitempty"`
}

// EmailSummary is the shape returned by email search/list operations. To is
// only populated when the caller needs include/exclude list IDs off a past
// send (see audience/last_sent.go) — HubSpot's list-search response includes
// it inline, no extra per-email GET required.
type EmailSummary struct {
	ID           string          `json:"id"`
	Name         string          `json:"name"`
	Subject      string          `json:"subject"`
	State        string          `json:"state"`
	Type         string          `json:"type"`
	PublishDate  string          `json:"publishDate,omitempty"`
	UpdatedAt    string          `json:"updatedAt,omitempty"`
	Campaign     string          `json:"campaign,omitempty"`
	CampaignName string          `json:"campaignName,omitempty"`
	From         EmailFrom       `json:"from,omitempty"`
	To           EmailRecipients `json:"to,omitempty"`
}

// EmailDetails is the full GET /marketing/v3/emails/{id} shape used across
// clone/settings/send-list flows.
type EmailDetails struct {
	ID           string          `json:"id"`
	Name         string          `json:"name"`
	Subject      string          `json:"subject"`
	State        string          `json:"state"`
	Type         string          `json:"type"`
	Campaign     string          `json:"campaign,omitempty"`
	CampaignName string          `json:"campaignName,omitempty"`
	From         EmailFrom       `json:"from,omitempty"`
	Settings     EmailFrom       `json:"settings,omitempty"`
	FromEmail    string          `json:"fromEmail,omitempty"`
	To           EmailRecipients `json:"to,omitempty"`
}

// ResolvedFrom returns the effective from-name/reply-to, preferring "from"
// over "settings" when both are set (matches Python's precedence).
func (e EmailDetails) ResolvedFrom() EmailFrom {
	if e.From.FromName != "" || e.From.ReplyTo != "" {
		return e.From
	}
	return e.Settings
}

// ClonedEmail is the result of HubSpotEmailClient.CloneEmail.
type ClonedEmail struct {
	EmailID  string `json:"email_id"`
	Name     string `json:"name"`
	State    string `json:"state"`
	DraftURL string `json:"draft_url"`
}

// CampaignUTM is the result of HubSpotEmailClient.GetCampaignUTM.
type CampaignUTM struct {
	Name           string `json:"hs_name"`
	UTM            string `json:"hs_utm"`
	CampaignStatus string `json:"hs_campaign_status"`
}

// ListInfo describes a HubSpot contact list (CRM v3 "lists" endpoint).
// ProcessingType is one of MANUAL/SNAPSHOT/DYNAMIC, or empty when the list
// could not be classified (see HubSpotListClient.GetListProcessingType).
type ListInfo struct {
	ID             string        `json:"id"`
	Name           string        `json:"name"`
	Size           int           `json:"size"`
	ProcessingType string        `json:"processingType,omitempty"`
	FilterBranch   *FilterBranch `json:"filterBranch,omitempty"`
}

// CreatedList is the result of HubSpotListClient.CreateList.
type CreatedList struct {
	ListID     string `json:"listId"`
	Name       string `json:"name"`
	Size       int    `json:"size"`
	HubSpotURL string `json:"hubspot_url"`
}

// FilterOperation is a PROPERTY filter's operation clause.
type FilterOperation struct {
	Operator                     string   `json:"operator"`
	IncludeObjectsWithNoValueSet bool     `json:"includeObjectsWithNoValueSet"`
	Values                       []string `json:"values,omitempty"`
	OperationType                string   `json:"operationType,omitempty"`
}

// Filter is a single leaf filter inside a FilterBranch: either an IN_LIST
// filter (ListID/Operator set, Operator is "IN_LIST" or "NOT_IN_LIST") or a
// PROPERTY filter (Property/Operation set).
type Filter struct {
	FilterType string           `json:"filterType"`
	ListID     string           `json:"listId,omitempty"`
	Operator   string           `json:"operator,omitempty"`
	Property   string           `json:"property,omitempty"`
	Operation  *FilterOperation `json:"operation,omitempty"`
}

// FilterBranch mirrors HubSpot's recursive list-filter tree:
// {"filterBranchType": "OR"|"AND"|"UNIFIED_EVENTS", "filterBranches": [...],
//
//	"filters": [...], "operator": ..., "eventTypeId": ...}. The last two
//
// fields only appear on UNIFIED_EVENTS (custom-event) branches.
type FilterBranch struct {
	FilterBranchType string         `json:"filterBranchType"`
	FilterBranches   []FilterBranch `json:"filterBranches,omitempty"`
	Filters          []Filter       `json:"filters,omitempty"`
	Operator         string         `json:"operator,omitempty"`
	EventTypeID      string         `json:"eventTypeId,omitempty"`
}

// EventTypeDef is a HubSpot custom-event type definition
// (GET /events/v3/event-definitions).
type EventTypeDef struct {
	FullyQualifiedName string   `json:"fullyQualifiedName"`
	Label              string   `json:"label"`
	Name               string   `json:"name"`
	Properties         []string `json:"properties,omitempty"`
}
