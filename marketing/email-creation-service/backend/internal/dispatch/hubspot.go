// Package dispatch holds outbound adapters — one file per external system,
// each implementing one or more domain ports. Provider-specific quirks
// (auth, pagination, payload shaping) are isolated here so service/ code
// never has to know about them.
package dispatch

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/filteroptimizer"
)

const hubspotBaseURL = "https://api.hubapi.com"

// flexInt unmarshals a JSON number or a JSON string containing digits into
// an int — HubSpot's list-search additionalProperties.hs_list_size comes
// back as a string, unlike every other numeric field in the same response,
// so a plain `int` field silently fails json.Unmarshal on every entry.
type flexInt int

func (f *flexInt) UnmarshalJSON(data []byte) error {
	if len(data) == 0 || string(data) == "null" {
		*f = 0
		return nil
	}
	if data[0] == '"' {
		var s string
		if err := json.Unmarshal(data, &s); err != nil {
			return err
		}
		if s == "" {
			*f = 0
			return nil
		}
		n, err := strconv.Atoi(s)
		if err != nil {
			return err
		}
		*f = flexInt(n)
		return nil
	}
	var n int
	if err := json.Unmarshal(data, &n); err != nil {
		return err
	}
	*f = flexInt(n)
	return nil
}

// ilsProcessingTypes are the CRM v3 processingType values that route
// through the ILS (contactIlsLists) namespace rather than legacy
// contactLists. Matches Python's _ILS_PROCESSING_TYPES.
var ilsProcessingTypes = map[string]bool{
	"DYNAMIC":  true,
	"MANUAL":   true,
	"SNAPSHOT": true,
}

// HubSpotClient is the single consolidated HubSpot adapter, implementing
// both domain.HubSpotEmailClient and domain.HubSpotListClient. This
// replaces 3 independent Python clients that each reimplemented the same
// Bearer-auth REST calls.
type HubSpotClient struct {
	httpClient *http.Client
	token      string
	portalID   string

	// assetTag, if non-empty, is appended to every list name this client
	// creates (mirrors config.TagAssetName / Python's tag_asset_name, applied
	// at the same call site hubspot_create_list applies it).
	assetTag string

	// baseURLOverride replaces hubspotBaseURL when set — test-only seam.
	baseURLOverride string
}

var (
	_ domain.HubSpotEmailClient = (*HubSpotClient)(nil)
	_ domain.HubSpotListClient  = (*HubSpotClient)(nil)
)

// NewHubSpotClient builds a HubSpot adapter. token is HUBSPOT_ACCESS_TOKEN,
// portalID is HUBSPOT_PORTAL_ID (used only to build human-facing HubSpot
// app URLs, never sent in API requests).
func NewHubSpotClient(token, portalID, assetTag string) *HubSpotClient {
	return &HubSpotClient{
		httpClient: &http.Client{Timeout: 30 * time.Second},
		token:      token,
		portalID:   portalID,
		assetTag:   assetTag,
	}
}

// tagAssetName appends assetTag to name, matching config.TagAssetName.
func (c *HubSpotClient) tagAssetName(name string) string {
	if c.assetTag == "" || name == "" {
		return name
	}
	suffix := " [" + c.assetTag + "]"
	if strings.HasSuffix(name, suffix) {
		return name
	}
	return name + suffix
}

// --- low-level request helpers -------------------------------------------

func (c *HubSpotClient) do(ctx context.Context, method, path string, query url.Values, body any) (*http.Response, []byte, error) {
	base := hubspotBaseURL
	if c.baseURLOverride != "" {
		base = c.baseURLOverride
	}
	u := base + path
	if len(query) > 0 {
		u += "?" + query.Encode()
	}

	var reader io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return nil, nil, fmt.Errorf("encode request: %w", err)
		}
		reader = bytes.NewReader(b)
	}

	req, err := http.NewRequestWithContext(ctx, method, u, reader)
	if err != nil {
		return nil, nil, fmt.Errorf("build request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+c.token)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, nil, fmt.Errorf("%s %s: %w", method, path, err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return resp, nil, fmt.Errorf("read response: %w", err)
	}
	return resp, respBody, nil
}

// request performs the call and unmarshals a 2xx JSON body into out (which
// may be nil for no-content responses). Non-2xx responses are mapped to
// domain sentinel errors, wrapped with the response body for diagnostics.
func (c *HubSpotClient) request(ctx context.Context, method, path string, query url.Values, body, out any) error {
	resp, respBody, err := c.do(ctx, method, path, query, body)
	if err != nil {
		return err
	}
	if resp.StatusCode == http.StatusNotFound {
		return fmt.Errorf("%s %s: %w", method, path, domain.ErrNotFound)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		snippet := string(respBody)
		if len(snippet) > 500 {
			snippet = snippet[:500]
		}
		return fmt.Errorf("%s %s: HTTP %d: %s: %w", method, path, resp.StatusCode, snippet, domain.ErrUpstream)
	}
	if out == nil || len(respBody) == 0 {
		return nil
	}
	if err := json.Unmarshal(respBody, out); err != nil {
		return fmt.Errorf("decode response from %s %s: %w", method, path, err)
	}
	return nil
}

// --- HubSpotEmailClient ----------------------------------------------------

func (c *HubSpotClient) GetEmailDetails(ctx context.Context, emailID string) (*model.EmailDetails, error) {
	var out model.EmailDetails
	if err := c.request(ctx, http.MethodGet, "/marketing/v3/emails/"+emailID, nil, nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

func (c *HubSpotClient) SearchEmails(ctx context.Context, opts domain.EmailSearchOptions) ([]model.EmailSummary, error) {
	limit := opts.Limit
	if limit <= 0 {
		limit = 50
	}
	orderBy := opts.OrderBy
	if orderBy == "" {
		orderBy = "-publishDate"
	}
	q := url.Values{
		"limit":   {strconv.Itoa(limit)},
		"orderBy": {orderBy},
	}
	if opts.NameContains != "" {
		q.Set("name__icontains", opts.NameContains)
	}

	var page struct {
		Results []model.EmailSummary `json:"results"`
	}
	if err := c.request(ctx, http.MethodGet, "/marketing/v3/emails", q, nil, &page); err != nil {
		return nil, err
	}
	if !opts.PublishedOnly {
		return page.Results, nil
	}

	filtered := make([]model.EmailSummary, 0, len(page.Results))
	for _, e := range page.Results {
		if e.State == "PUBLISHED" {
			filtered = append(filtered, e)
		}
	}
	return filtered, nil
}

func (c *HubSpotClient) CloneEmail(ctx context.Context, sourceEmailID, cloneName string) (*model.ClonedEmail, error) {
	body := map[string]any{
		"id":        sourceEmailID,
		"cloneName": c.tagAssetName(cloneName),
		"language":  "en",
	}
	var created struct {
		ID    string `json:"id"`
		Name  string `json:"name"`
		State string `json:"state"`
	}
	if err := c.request(ctx, http.MethodPost, "/marketing/v3/emails/clone", nil, body, &created); err != nil {
		return nil, err
	}
	if created.ID == "" {
		return nil, fmt.Errorf("clone email %s: no id in response: %w", sourceEmailID, domain.ErrUpstream)
	}

	// Verification GET, matching the Python client's post-clone check.
	verified, err := c.GetEmailDetails(ctx, created.ID)
	if err != nil {
		return nil, fmt.Errorf("verify cloned email %s: %w", created.ID, err)
	}
	if verified.ID == "" {
		return nil, fmt.Errorf("clone email %s: verification returned no id: %w", sourceEmailID, domain.ErrUpstream)
	}

	return &model.ClonedEmail{
		EmailID:  created.ID,
		Name:     created.Name,
		State:    created.State,
		DraftURL: fmt.Sprintf("https://app.hubspot.com/email/%s/edit/%s/settings", c.portalID, created.ID),
	}, nil
}

func (c *HubSpotClient) CreateABVariation(ctx context.Context, emailID, variationName string) (*model.EmailSummary, error) {
	body := map[string]any{
		"contentId":     emailID,
		"variationName": variationName,
	}
	var out model.EmailSummary
	if err := c.request(ctx, http.MethodPost, "/marketing/v3/emails/ab-test/create-variation", nil, body, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// UpdateEmailSettings applies only the non-nil fields. PreviewText requires
// a read-merge-write against the email's current content object so we
// don't clobber flexAreas/templatePath — matching the Python client's
// merge-then-patch pattern.
func (c *HubSpotClient) UpdateEmailSettings(ctx context.Context, emailID string, update domain.EmailSettingsUpdate) error {
	patch := map[string]any{}
	if update.Subject != nil {
		patch["subject"] = *update.Subject
	}
	if update.Type != nil {
		patch["type"] = *update.Type
	}
	if update.FromName != nil || update.ReplyTo != nil {
		from := map[string]any{}
		if update.FromName != nil {
			from["fromName"] = *update.FromName
		}
		if update.ReplyTo != nil {
			from["replyTo"] = *update.ReplyTo
		}
		patch["from"] = from
	}
	if update.PreviewText != nil {
		// Matches the Python client: a failure fetching current content
		// degrades to a partial, widget-only content payload rather than
		// aborting the whole settings update (subject/type/from/replyTo
		// changes in this same patch would otherwise be lost too).
		var content map[string]any
		var current struct {
			Content map[string]any `json:"content"`
		}
		if err := c.request(ctx, http.MethodGet, "/marketing/v3/emails/"+emailID, nil, nil, &current); err == nil {
			content = current.Content
		}
		if content == nil {
			content = map[string]any{}
		}
		widgets, _ := content["widgets"].(map[string]any)
		if widgets == nil {
			widgets = map[string]any{}
		}
		widgets["preview_text"] = map[string]any{
			"body": map[string]any{"value": *update.PreviewText},
		}
		content["widgets"] = widgets
		patch["content"] = content
	}
	if len(patch) == 0 {
		return nil
	}
	return c.request(ctx, http.MethodPatch, "/marketing/v3/emails/"+emailID, nil, patch, nil)
}

// SetEmailSendList sends a complete replacement "to" object (never a
// partial patch) since HubSpot keeps omitted sub-fields — a partial patch
// would leave stale contactIds/lists lingering from a cloned email. Exactly
// one of ContactLists/ContactIlsLists may be non-empty; mixing both
// namespaces in one call is rejected by HubSpot.
func (c *HubSpotClient) SetEmailSendList(ctx context.Context, emailID string, update domain.SendListUpdate) (model.EmailRecipients, error) {
	hasLegacy := len(update.ContactLists.Include) > 0 || len(update.ContactLists.Exclude) > 0
	hasILS := len(update.ContactIlsLists.Include) > 0 || len(update.ContactIlsLists.Exclude) > 0
	if hasLegacy && hasILS {
		return model.EmailRecipients{}, fmt.Errorf("set send list for email %s: cannot mix legacy contactLists and ILS contactIlsLists in one call: %w", emailID, domain.ErrInvalidInput)
	}

	// contactIds is always cleared, matching Python's set_email_send_list —
	// omitting it would leave stale individually-added contacts from the
	// clone source, since HubSpot's PATCH keeps omitted sub-fields as-is.
	to := map[string]any{
		"contactIds": map[string]any{"include": []string{}, "exclude": []string{}},
	}
	if hasLegacy {
		to["contactLists"] = update.ContactLists
	}
	if hasILS {
		to["contactIlsLists"] = update.ContactIlsLists
	}

	var resp struct {
		To model.EmailRecipients `json:"to"`
	}
	if err := c.request(ctx, http.MethodPatch, "/marketing/v3/emails/"+emailID, nil, map[string]any{"to": to}, &resp); err != nil {
		return model.EmailRecipients{}, err
	}
	return resp.To, nil
}

func (c *HubSpotClient) GetCampaign(ctx context.Context, emailID string) (string, string, error) {
	var out struct {
		Campaign     string `json:"campaign"`
		CampaignName string `json:"campaignName"`
	}
	if err := c.request(ctx, http.MethodGet, "/marketing/v3/emails/"+emailID, nil, nil, &out); err != nil {
		return "", "", err
	}
	return out.Campaign, out.CampaignName, nil
}

func (c *HubSpotClient) GetCampaignUTM(ctx context.Context, campaignGUID string) (*model.CampaignUTM, error) {
	q := url.Values{"properties": {"hs_name,hs_utm,hs_campaign_status"}}
	var out struct {
		Properties model.CampaignUTM `json:"properties"`
	}
	if err := c.request(ctx, http.MethodGet, "/marketing/v3/campaigns/"+campaignGUID, q, nil, &out); err != nil {
		return nil, err
	}
	return &out.Properties, nil
}

// --- HubSpotListClient ------------------------------------------------------

func (c *HubSpotClient) SearchLists(ctx context.Context, query string, limit int) ([]model.ListInfo, error) {
	if limit <= 0 {
		limit = 20
	}
	body := map[string]any{
		"query":           query,
		"count":           limit,
		"processingTypes": []string{"MANUAL", "SNAPSHOT", "DYNAMIC"},
	}
	var out struct {
		Lists []json.RawMessage `json:"lists"`
	}
	if err := c.request(ctx, http.MethodPost, "/crm/v3/lists/search", nil, body, &out); err != nil {
		return nil, err
	}

	lists := make([]model.ListInfo, 0, len(out.Lists))
	for _, raw := range out.Lists {
		var l struct {
			ListID               string `json:"listId"`
			ID                   string `json:"id"`
			Name                 string `json:"name"`
			Size                 int    `json:"size"`
			ProcessingType       string `json:"processingType"`
			AdditionalProperties struct {
				HsListSize flexInt `json:"hs_list_size"`
			} `json:"additionalProperties"`
		}
		if err := json.Unmarshal(raw, &l); err != nil {
			continue
		}
		id := l.ListID
		if id == "" {
			id = l.ID
		}
		size := l.Size
		if size == 0 {
			size = int(l.AdditionalProperties.HsListSize)
		}
		lists = append(lists, model.ListInfo{ID: id, Name: l.Name, Size: size, ProcessingType: l.ProcessingType})
	}
	return lists, nil
}

// SearchListsByName ports integrations/hubspot.py's search_lists (distinct
// from SearchLists, which ports audience_tools.py's hubspot_search_lists).
func (c *HubSpotClient) SearchListsByName(ctx context.Context, query string, limit int) ([]model.ListInfo, error) {
	if len(query) < 2 {
		return []model.ListInfo{}, nil
	}
	if limit <= 0 {
		limit = 10
	}
	body := map[string]any{
		"query":           query,
		"count":           limit,
		"processingTypes": []string{"MANUAL", "SNAPSHOT", "DYNAMIC"},
	}
	var out struct {
		Lists []json.RawMessage `json:"lists"`
	}
	if err := c.request(ctx, http.MethodPost, "/crm/v3/lists/search", nil, body, &out); err != nil {
		return nil, err
	}

	lists := make([]model.ListInfo, 0, len(out.Lists))
	for _, raw := range out.Lists {
		var l struct {
			ListID               string `json:"listId"`
			ID                   string `json:"id"`
			Name                 string `json:"name"`
			ProcessingType       string `json:"processingType"`
			AdditionalProperties struct {
				HsListSize flexInt `json:"hs_list_size"`
			} `json:"additionalProperties"`
		}
		if err := json.Unmarshal(raw, &l); err != nil {
			continue
		}
		id := l.ListID
		if id == "" {
			id = l.ID
		}
		if l.Name == "" || id == "" {
			continue
		}
		lists = append(lists, model.ListInfo{
			ID:             id,
			Name:           l.Name,
			Size:           int(l.AdditionalProperties.HsListSize),
			ProcessingType: l.ProcessingType,
		})
	}
	return lists, nil
}

// getListRaw fetches GET /crm/v3/lists/{id} and unwraps HubSpot's
// inconsistent response shape, which is sometimes flat and sometimes
// wrapped as {"list": {...}}.
func (c *HubSpotClient) getListRaw(ctx context.Context, listID string, includeFilters bool) (map[string]any, error) {
	q := url.Values{}
	if includeFilters {
		q.Set("includeFilters", "true")
	}
	var raw map[string]any
	if err := c.request(ctx, http.MethodGet, "/crm/v3/lists/"+listID, q, nil, &raw); err != nil {
		return nil, err
	}
	if inner, ok := raw["list"].(map[string]any); ok {
		return inner, nil
	}
	return raw, nil
}

func (c *HubSpotClient) GetList(ctx context.Context, listID string) (*model.ListInfo, error) {
	raw, err := c.getListRaw(ctx, listID, true)
	if err != nil {
		return nil, err
	}
	info := model.ListInfo{ID: listID}
	if v, ok := raw["listId"].(string); ok {
		info.ID = v
	}
	if v, ok := raw["name"].(string); ok {
		info.Name = v
	}
	if v, ok := raw["size"].(float64); ok {
		info.Size = int(v)
	}
	if v, ok := raw["processingType"].(string); ok {
		info.ProcessingType = v
	}
	if fb, ok := raw["filterBranch"]; ok && fb != nil {
		b, err := json.Marshal(fb)
		if err == nil {
			var branch model.FilterBranch
			if err := json.Unmarshal(b, &branch); err == nil {
				info.FilterBranch = &branch
			}
		}
	}
	return &info, nil
}

// GetLegacyListName looks up a legacy (v1) contact list by ID — used when a
// list ID doesn't resolve in CRM v3 (see GetListProcessingType returning
// "UNKNOWN"). Returns exists=false on 404 or when HubSpot reports the list
// as deleted, matching Python's _legacy_v1_list_name.
func (c *HubSpotClient) GetLegacyListName(ctx context.Context, listID string) (string, bool, error) {
	var out struct {
		Name    string `json:"name"`
		Deleted bool   `json:"deleted"`
	}
	if err := c.request(ctx, http.MethodGet, "/contacts/v1/lists/"+listID, nil, nil, &out); err != nil {
		if isNotFound(err) {
			return "", false, nil
		}
		return "", false, err
	}
	if out.Deleted {
		return "", false, nil
	}
	return out.Name, true, nil
}

// GetListProcessingType returns "UNKNOWN" when the list isn't found in CRM
// v3 (a 404 there means it's a legacy list, not an error condition).
func (c *HubSpotClient) GetListProcessingType(ctx context.Context, listID string) (string, error) {
	raw, err := c.getListRaw(ctx, listID, false)
	if err != nil {
		if isNotFound(err) {
			return "UNKNOWN", nil
		}
		return "", err
	}
	if v, ok := raw["processingType"].(string); ok && v != "" {
		return v, nil
	}
	return "UNKNOWN", nil
}

func (c *HubSpotClient) IsILSList(ctx context.Context, listID string) (bool, error) {
	pt, err := c.GetListProcessingType(ctx, listID)
	if err != nil {
		return false, err
	}
	return ilsProcessingTypes[pt], nil
}

func (c *HubSpotClient) ListMembershipIDs(ctx context.Context, listID string, capPages int) ([]string, error) {
	if capPages <= 0 {
		capPages = 100
	}
	var ids []string
	after := ""
	for page := 0; page < capPages; page++ {
		q := url.Values{"limit": {"250"}}
		if after != "" {
			q.Set("after", after)
		}
		var out struct {
			Results []struct {
				RecordID string `json:"recordId"`
			} `json:"results"`
			Paging struct {
				Next struct {
					After string `json:"after"`
				} `json:"next"`
			} `json:"paging"`
		}
		if err := c.request(ctx, http.MethodGet, "/crm/v3/lists/"+listID+"/memberships", q, nil, &out); err != nil {
			return nil, err
		}
		for _, r := range out.Results {
			ids = append(ids, r.RecordID)
		}
		if out.Paging.Next.After == "" {
			break
		}
		after = out.Paging.Next.After
	}
	return ids, nil
}

func (c *HubSpotClient) CreateList(ctx context.Context, name string, filterBranch model.FilterBranch) (*model.CreatedList, error) {
	filterBranch = filteroptimizer.New(false).Optimize(filterBranch)
	name = c.tagAssetName(name)
	body := map[string]any{
		"name":           name,
		"objectTypeId":   "0-1",
		"processingType": "DYNAMIC",
		"filterBranch":   filterBranch,
	}
	var raw map[string]any
	if err := c.request(ctx, http.MethodPost, "/crm/v3/lists/", nil, body, &raw); err != nil {
		return nil, err
	}

	data := raw
	if inner, ok := raw["list"].(map[string]any); ok {
		data = inner
	}
	listID, _ := data["listId"].(string)
	if listID == "" {
		if id, ok := raw["listId"].(string); ok {
			listID = id
		}
	}
	if listID == "" {
		return nil, fmt.Errorf("create list %q: no listId in response: %w", name, domain.ErrUpstream)
	}
	size := 0
	_, hasSize := data["size"]
	if v, ok := data["size"].(float64); ok {
		size = int(v)
	}
	return &model.CreatedList{
		ListID:     listID,
		Name:       name,
		Size:       size,
		HasSize:    hasSize,
		HubSpotURL: fmt.Sprintf("https://app.hubspot.com/contacts/%s/objectLists/%s/filters", c.portalID, listID),
	}, nil
}

func (c *HubSpotClient) UpdateListFilters(ctx context.Context, listID string, filterBranch model.FilterBranch) error {
	filterBranch = filteroptimizer.New(false).Optimize(filterBranch)
	body := map[string]any{"filterBranch": filterBranch}
	return c.request(ctx, http.MethodPut, "/crm/v3/lists/"+listID+"/filter-branch", nil, body, nil)
}

func (c *HubSpotClient) GetEventTypes(ctx context.Context) ([]model.EventTypeDef, error) {
	q := url.Values{"limit": {"100"}, "includeProperties": {"true"}}
	var out struct {
		Results []model.EventTypeDef `json:"results"`
	}
	if err := c.request(ctx, http.MethodGet, "/events/v3/event-definitions", q, nil, &out); err != nil {
		return nil, err
	}
	return out.Results, nil
}

func isNotFound(err error) bool {
	return err != nil && errors.Is(err, domain.ErrNotFound)
}
