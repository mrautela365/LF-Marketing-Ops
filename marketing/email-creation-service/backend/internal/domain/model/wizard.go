// Package model's wizard.go holds the request/response and session shapes
// for the email-creation wizard (plan → content → clone → chat), porting
// backend/models.py + backend/core/session.py. Field names/json tags match
// the Python API exactly so the existing Angular frontend keeps working
// unmodified.
package model

// SessionState is the in-memory session mirrored across the wizard's turns,
// porting core/session.py's SessionState. Meta holds the many loosely-typed
// working fields the Python version stashes in a dict — kept as a
// map[string]any here for the same reason: these values pass straight
// through to JSON responses without ever being read back typed by Go code
// outside the wizard services themselves.
type SessionState struct {
	SessionID string `json:"session_id"`
	Phase     string `json:"phase"` // planning | cloned | complete
	EmailID   string `json:"email_id,omitempty"`
	DraftURL  string `json:"draft_url,omitempty"`

	// Messages is the full agentic conversation history passed to
	// LLMGateway.RunAgent on every subsequent turn (plan/chat), letting the
	// model see what it already told the user.
	Messages []AgentMessage `json:"-"`

	Meta map[string]any `json:"-"`

	// EmailIDsAllowed scopes the clone-turn tool-execution safety gate
	// per-session rather than process-global — the Python version keeps
	// this as a global, which is a cross-session race under concurrent
	// requests (see core/agent.py's _session_email_id/_session_email_ids_allowed).
	EmailIDsAllowed map[string]bool `json:"-"`
}

// AgentMessage is one turn in the wizard's conversation history — a
// session-scoped alias of the LLM gateway's domain.Message so callers don't
// need to import the llm package just to build a SessionState.
type AgentMessage struct {
	Role    string
	Content string
}

func NewSessionState(sessionID string) *SessionState {
	return &SessionState{
		SessionID:       sessionID,
		Phase:           "planning",
		Meta:            map[string]any{},
		EmailIDsAllowed: map[string]bool{},
	}
}

// --- Plan ------------------------------------------------------------------

// PlanRequest is POST /api/plan-start and /api/plan's body. ExtraContext and
// IsTransactional are accepted for parity with the Python API shape but are
// confirmed dead fields there too (never read by the plan pipeline) — kept
// here only so the frontend's existing request body doesn't need to change.
type PlanRequest struct {
	URL             string `json:"url"`
	ExtraContext    string `json:"extra_context,omitempty"`
	EmailType       string `json:"email_type,omitempty"`
	IsTransactional *bool  `json:"is_transactional,omitempty"`
	ProgressToken   string `json:"progress_token,omitempty"`
}

// PlanStartResponse is the immediate (pre-work) response to /api/plan-start.
type PlanStartResponse struct {
	Token string `json:"token"`
}

// SourceEmailRef names the past-campaign email the plan/clone flow will use.
type SourceEmailRef struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

// PlanResult is the object returned by /api/plan and carried as
// {"type":"plan_done","result": ...} over /api/progress/{token}.
type PlanResult struct {
	SessionID    string          `json:"session_id"`
	Message      string          `json:"message"`
	Phase        string          `json:"phase"`
	Mode         string          `json:"mode"`
	SourceEmail  *SourceEmailRef `json:"source_email,omitempty"`
	Stage        map[string]any  `json:"stage,omitempty"`
	UTM          map[string]any  `json:"utm,omitempty"`
}

// ProgressEvent is one SSE frame on GET /api/progress/{token}. Extra keys
// (Done/Error) are only set by /api/generate-content's brief lines.
type ProgressEvent struct {
	Type   string `json:"type"` // brief | plan_done | error | heartbeat
	Text   string `json:"text,omitempty"`
	Result any    `json:"result,omitempty"`
	Done   bool   `json:"done,omitempty"`
	Error  bool   `json:"error,omitempty"`
}

// --- Content -----------------------------------------------------------------

// GenerateContentRequest is POST /api/generate-content's body.
type GenerateContentRequest struct {
	SessionID     string `json:"session_id"`
	ChangeRequest string `json:"change_request,omitempty"`
	ProgressToken string `json:"progress_token,omitempty"`
}

// EmailSection is one drag-and-drop content block, matching the shape the
// existing Angular UI already renders/edits (type + arbitrary fields).
type EmailSection map[string]any

// GeneratedContent is Variant B's output — reference-driven content built
// from real past-campaign emails (agent.generate_email_content).
type GeneratedContent struct {
	Subject     string         `json:"subject"`
	PreviewText string         `json:"preview_text"`
	HTML        string         `json:"html"`
	BodyHTML    string         `json:"body_html"`
	Sections    []EmailSection `json:"sections"`
	Sponsors    []Sponsor      `json:"sponsors,omitempty"`
	BannerURL   string         `json:"banner_url,omitempty"`
}

// AITemplateContent is Variant A's output — driven only by scraped event
// facts and the stage-based marketing-journey library, never by a past
// campaign email (agent.generate_ai_template_content). Mode is "ai-generated"
// on success or "failed" (with Error set) — a Variant A failure must never
// block Variant B, so callers treat "failed" as a non-fatal, displayable state.
type AITemplateContent struct {
	Subject      string         `json:"subject"`
	PreviewText  string         `json:"preview_text"`
	HTML         string         `json:"html"`
	BodyHTML     string         `json:"body_html"`
	Sections     []EmailSection `json:"sections"`
	Sponsors     []Sponsor      `json:"sponsors,omitempty"`
	BannerURL    string         `json:"banner_url,omitempty"`
	TemplateKey  string         `json:"template_key,omitempty"`
	StageName    string         `json:"stage_name,omitempty"`
	Mode         string         `json:"mode"` // ai-generated | failed
	Error        string         `json:"error,omitempty"`
}

// Sponsor is one sponsor logo scraped from the event page.
type Sponsor struct {
	Name string `json:"name"`
	Logo string `json:"logo_url"`
	URL  string `json:"url,omitempty"`
	Tier string `json:"tier,omitempty"` // tier1 | tier2
}

// GenerateContentResponse merges Variant B + Variant A fields, matching the
// flat dict main.py's /api/generate-content handler returns.
type GenerateContentResponse struct {
	SessionID string `json:"session_id"`

	Subject     string         `json:"subject"`
	PreviewText string         `json:"preview_text"`
	HTML        string         `json:"html"`
	BodyHTML    string         `json:"body_html"`
	Sections    []EmailSection `json:"sections"`
	Sponsors    []Sponsor      `json:"sponsors,omitempty"`
	BannerURL   string         `json:"banner_url,omitempty"`

	VariantASubject     string         `json:"variant_a_subject"`
	VariantAPreviewText string         `json:"variant_a_preview_text"`
	VariantAHTML        string         `json:"variant_a_html"`
	VariantABodyHTML    string         `json:"variant_a_body_html"`
	VariantASections    []EmailSection `json:"variant_a_sections"`
	VariantABannerURL   string         `json:"variant_a_banner_url,omitempty"`
	VariantATemplateKey string         `json:"variant_a_template_key,omitempty"`
	VariantAMode        string         `json:"variant_a_mode"`
}

// UpdateSectionsRequest is POST /api/update-sections's body — the sections
// the user kept after editing, rebuilt into HTML deterministically (no LLM
// call), matching agent._sections_to_html / _build_email_preview.
type UpdateSectionsRequest struct {
	SessionID string         `json:"session_id"`
	Sections  []EmailSection `json:"sections"`
}

// UpdateSectionsResponse is the rebuilt HTML after a manual section edit.
type UpdateSectionsResponse struct {
	SessionID     string `json:"session_id"`
	BodyHTML      string `json:"body_html"`
	GeneratedHTML string `json:"generated_html"`
}

// --- Clone / send list -------------------------------------------------------

// CloneRequest is POST /api/clone's body.
type CloneRequest struct {
	SessionID     string  `json:"session_id"`
	Approved      bool    `json:"approved"`
	Subject       *string `json:"subject,omitempty"`
	PreviewText   *string `json:"preview_text,omitempty"`
	SendListID    *string `json:"send_list_id,omitempty"`
}

// CloneResponse is the result of /api/clone — includes the A/B email ids
// once clone_turn's pipeline has run.
type CloneResponse struct {
	SessionID          string `json:"session_id"`
	Message            string `json:"message"`
	Phase              string `json:"phase"`
	EmailID            string `json:"email_id,omitempty"`
	DraftURL           string `json:"draft_url,omitempty"`
	VariantAEmailID    string `json:"variant_a_email_id,omitempty"`
	VariantADraftURL   string `json:"variant_a_draft_url,omitempty"`
	VariantBEmailID    string `json:"variant_b_email_id,omitempty"`
	VariantBDraftURL   string `json:"variant_b_draft_url,omitempty"`
	ValidationPassed   bool   `json:"validation_passed"`
	ValidationIssues   []string `json:"validation_issues,omitempty"`
}

// SetSendListRequest is POST /api/set-send-list's body. SendListIDs (plural)
// takes priority over SendListID (singular, back-compat) when both are set.
type SetSendListRequest struct {
	SessionID           string   `json:"session_id,omitempty"`
	EmailID              string   `json:"email_id,omitempty"`
	SendListID           string   `json:"send_list_id,omitempty"`
	SendListIDs          []string `json:"send_list_ids,omitempty"`
	SuppressionListIDs   []string `json:"suppression_list_ids,omitempty"`
}

// SetSendListResponse mirrors hubspot.SetEmailSendList's return shape.
type SetSendListResponse struct {
	Success    bool           `json:"success"`
	EmailID    string         `json:"email_id"`
	SendListID string         `json:"send_list_id"`
	ListType   string         `json:"list_type"`
	To         map[string]any `json:"to"`
}

// --- Chat --------------------------------------------------------------------

// ChatRequest is POST /api/chat's body — a free-form follow-up turn appended
// to the session's agentic conversation.
type ChatRequest struct {
	SessionID string `json:"session_id"`
	Message   string `json:"message"`
}

// ChatResponse is the result of a chat turn.
type ChatResponse struct {
	SessionID string `json:"session_id"`
	Message   string `json:"message"`
	Phase     string `json:"phase"`
	DraftURL  string `json:"draft_url,omitempty"`
}

// SessionSummary is GET /api/session/{id}'s response.
type SessionSummary struct {
	SessionID string         `json:"session_id"`
	Phase     string         `json:"phase"`
	Plan      map[string]any `json:"plan,omitempty"`
	EmailID   string         `json:"email_id,omitempty"`
	DraftURL  string         `json:"draft_url,omitempty"`
}
