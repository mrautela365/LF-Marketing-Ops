// emailcontent.go holds the shapes used by the DnD content-writer flow
// (get_email_content_text / update_email_content / validate_staged_email in
// integrations/hubspot.py). ContentSection is deliberately a loose,
// all-optional struct rather than a Go union type — it mirrors the
// heterogeneous per-type dicts the Python side produces/consumes
// (rich_text/button/image/image_row/divider/social_icons), and is used both
// as UpdateEmailContentInput's input shape (rich_text/button only) and as
// EmailContentText's richer output shape (all types).
package model

// SectionImage is one logo/image inside an "image_row" ContentSection.
type SectionImage struct {
	Src string `json:"src"`
	Alt string `json:"alt,omitempty"`
}

// ContentSection is one structured email-body component.
type ContentSection struct {
	Type string `json:"type"`

	// rich_text
	HTML string `json:"html,omitempty"`

	// button (output uses BackgroundColor/Destination; input uses Color/URL
	// pre-UTM-tagging)
	Text            string `json:"text,omitempty"`
	BackgroundColor string `json:"background_color,omitempty"`
	Destination     string `json:"destination,omitempty"`
	Color           string `json:"color,omitempty"`
	URL             string `json:"url,omitempty"`

	// image
	Src string `json:"src,omitempty"`
	Alt string `json:"alt,omitempty"`

	// image_row
	Images []SectionImage `json:"images,omitempty"`

	// divider
	Style  string `json:"style,omitempty"`
	Height int    `json:"height,omitempty"`

	// social_icons
	Networks []string `json:"networks,omitempty"`
}

// EmailContentText is the result of HubSpotEmailClient.GetEmailContentText —
// ports get_email_content_text.
type EmailContentText struct {
	Success     bool             `json:"success"`
	EmailID     string           `json:"email_id"`
	EmailName   string           `json:"email_name,omitempty"`
	Subject     string           `json:"subject,omitempty"`
	PreviewText string           `json:"preview_text,omitempty"`
	BodyText    string           `json:"body_text,omitempty"`
	BodyHTML    string           `json:"body_html,omitempty"`
	Sections    []ContentSection `json:"sections,omitempty"`
	Error       string           `json:"error,omitempty"`
}

// UpdateEmailContentResult is the result of HubSpotEmailClient.UpdateEmailContent.
type UpdateEmailContentResult struct {
	Success bool   `json:"success"`
	EmailID string `json:"email_id,omitempty"`
	Method  string `json:"method,omitempty"`
	Error   string `json:"error,omitempty"`
}

// ValidateStagedEmailResult is the result of HubSpotEmailClient.ValidateStagedEmail.
type ValidateStagedEmailResult struct {
	Valid   bool     `json:"valid"`
	Issues  []string `json:"issues"`
	Summary string   `json:"summary"`
}

// UTMResolution is the result of HubSpotEmailClient.ResolveUTMCampaign.
type UTMResolution struct {
	CampaignID   string `json:"campaign_id,omitempty"`
	CampaignName string `json:"campaign_name,omitempty"`
	UTMCampaign  string `json:"utm_campaign"`
	Source       string `json:"source"`
	UTMSource    string `json:"utm_source"`
	UTMMedium    string `json:"utm_medium"`
}

// EventEmailMatch is the result of HubSpotEmailClient.SearchEmailsForEvent.
type EventEmailMatch struct {
	Found              bool     `json:"found"`
	Message            string   `json:"message,omitempty"`
	EventMatch         bool     `json:"event_match,omitempty"`
	MatchedTier        string   `json:"matched_tier,omitempty"`
	LocaleFilter       string   `json:"locale_filter,omitempty"`
	MatchedEmailID     string   `json:"matched_email_id,omitempty"`
	MatchedEmailName   string   `json:"matched_email_name,omitempty"`
	MatchedScore       int      `json:"matched_score,omitempty"`
	FromName           string   `json:"from_name,omitempty"`
	FromAddress        string   `json:"from_address,omitempty"`
	EmailType          string   `json:"email_type,omitempty"`
	SuppressionListIDs []string `json:"suppression_list_ids,omitempty"`
	IncludedListIDs    []string `json:"included_list_ids,omitempty"`
}
