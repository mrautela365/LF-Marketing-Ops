package model

// DiscoveredList is one HubSpot list surfaced by the (LLM-driven, phase 5)
// discovery agent, classified into one of the 5 signals.
type DiscoveredList struct {
	ListID string `json:"list_id"`
	Name   string `json:"name"`
	Signal string `json:"signal"` // project_opt_in | lf_newsletter_opt_in | event_registration | education_enrollment | page_view | event_speakers | uncertain
	Size   *int   `json:"size,omitempty"`
	Reason string `json:"reason,omitempty"`
	Type   string `json:"list_type,omitempty"` // HubSpot processingType: DYNAMIC | MANUAL | SNAPSHOT
	Scope  string `json:"scope,omitempty"`     // current | past | current_past — only meaningful when Signal == event_speakers
}

// ComposeMasterListRequest is the /api/audience-builder/compose-master body.
type ComposeMasterListRequest struct {
	ListIDs        []string `json:"list_ids"`
	Name           string   `json:"name,omitempty"`
	EventURL       string   `json:"event_url,omitempty"`
	BrandShort     string   `json:"brand_short,omitempty"`
	EventName      string   `json:"event_name,omitempty"`
	ExcludeListIDs []string `json:"exclude_list_ids,omitempty"`
}

// ComposeMasterListResponse is the result of composing (and optionally
// suppressing) a master list. Size fields are "unknown" (string) when
// HubSpot's create-list response didn't include a size — Go's json package
// can't emit an int|string union field, so Size is left as a string here
// (matching the "unknown" fallback; a real size is formatted as its digits).
type ComposeMasterListResponse struct {
	ListID                string   `json:"list_id"`
	Name                  string   `json:"name"`
	HubSpotURL            string   `json:"hubspot_url"`
	Size                  string   `json:"size"`
	SourceListIDs         []string `json:"source_list_ids"`
	SuppressionListID     string   `json:"suppression_list_id,omitempty"`
	SuppressionName       string   `json:"suppression_name,omitempty"`
	SuppressionHubSpotURL string   `json:"suppression_hubspot_url,omitempty"`
	SuppressionSize       string   `json:"suppression_size,omitempty"`
}

// SuppressionList is a standard hygiene suppression/opt-out list resolved by
// name search (see audience.FindStandardSuppressionLists).
type SuppressionList struct {
	Key      string `json:"key"`
	Label    string `json:"label"`
	ListID   string `json:"list_id"`
	Name     string `json:"name"`
	Size     *int   `json:"size,omitempty"`
	Category string `json:"category"` // standard | brand | event_specific
}

// ExistingMasterList is a previously-built master list for this event,
// surfaced so the user can reuse it (see audience.FindExistingMasterLists).
type ExistingMasterList struct {
	ListID     string `json:"list_id"`
	Name       string `json:"name"`
	Size       *int   `json:"size,omitempty"`
	HubSpotURL string `json:"hubspot_url"`
}

// PreviewCountRequest is the /api/audience-builder/preview-count body.
type PreviewCountRequest struct {
	ListIDs []string `json:"list_ids"`
}

// PreviewCountResponse is the de-duplicated (or estimated) contact count
// across a set of lists (see audience.UnionSize).
type PreviewCountResponse struct {
	Exact    bool   `json:"exact"`
	Estimate int    `json:"estimate"`
	Count    int    `json:"count"`
	Reason   string `json:"reason,omitempty"`
}

// QaRunRequest is the /api/audience-builder/qa/run body.
type QaRunRequest struct {
	ListRef   string `json:"list_ref"` // HubSpot list URL, bare numeric ID, or list name
	TargetsEU bool   `json:"targets_eu,omitempty"`
	TargetsCA bool   `json:"targets_ca,omitempty"`
}

// ListBrief is a list ID resolved to display info — used both for last-sent
// email include/exclude lists and QA list-search candidates.
type ListBrief struct {
	ListID               string `json:"list_id"`
	Name                 string `json:"name"`
	Size                 *int   `json:"size,omitempty"`
	Missing              bool   `json:"missing,omitempty"`
	ResolvedFromLegacyID string `json:"resolved_from_legacy_id,omitempty"`
}

// LastSentEmail is one previously-sent marketing email for an event, with
// its included/suppression lists resolved to display info.
type LastSentEmail struct {
	EmailID          string      `json:"email_id"`
	EmailName        string      `json:"email_name"`
	SentAt           string      `json:"sent_at"`
	HubSpotURL       string      `json:"hubspot_url"`
	IncludedLists    []ListBrief `json:"included_lists"`
	SuppressionLists []ListBrief `json:"suppression_lists"`
}

// ResolveListRefCandidate is one ambiguous match when resolving a list
// reference by name yields more than one result.
type ResolveListRefCandidate struct {
	ListID string `json:"list_id"`
	Name   string `json:"name"`
	Size   *int   `json:"size,omitempty"`
}

// ResolvedListRef is the result of resolving a list URL/ID/name. Candidates
// is only populated (and ListID left empty) when disambiguation is needed.
type ResolvedListRef struct {
	ListID     string                    `json:"list_id"`
	Name       string                    `json:"name"`
	Candidates []ResolveListRefCandidate `json:"candidates,omitempty"`
}

// QaFinding is one issue surfaced by a QA check.
type QaFinding struct {
	Severity string `json:"severity"`
	Message  string `json:"message"`
	Fix      string `json:"fix"`
}

// QaCheckResult is the outcome of one QA check (signal mapping, suppression,
// exclusion completeness).
type QaCheckResult struct {
	Verdict  string      `json:"verdict"`
	Findings []QaFinding `json:"findings"`

	// Applied is only set by check_gdpr_casl_suppression.
	Applied *QaSuppressionApplied `json:"applied,omitempty"`
	// ExclusionCount is only set by check_exclusion_completeness.
	ExclusionCount *int `json:"exclusion_count,omitempty"`
}

// QaSuppressionApplied reports which suppression categories were detected.
type QaSuppressionApplied struct {
	GDPR   bool `json:"gdpr"`
	OptOut bool `json:"opt_out"`
}

// QaResult is the full result of run_qa_on_list.
type QaResult struct {
	ListID     string                   `json:"list_id"`
	Name       string                   `json:"name"`
	HubSpotURL string                   `json:"hubspot_url"`
	Checks     map[string]QaCheckResult `json:"checks"`
	Findings   []QaFinding              `json:"findings"`
	Overall    string                   `json:"overall"`
}
