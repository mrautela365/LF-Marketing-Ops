// Shared TypeScript types for the email-creation-ui workspace.
//
// This mirrors lfx-self-serve's packages/shared pattern of sharing types
// between apps in a Turborepo/yarn(or npm)-workspaces monorepo. For this
// skeleton pass it only contains the couple of types the app actually
// consumes from the Go backend, matching the JSON shapes emitted by
// services/backend (see gen/http/openapi3.json for StatusResult, and
// cmd/emailcreationskill/audience_handlers.go for the lists/search route).

/**
 * Response body for `GET /api/status` (Goa-generated `status` service,
 * see services/backend/gen/status/service.go StatusResult).
 */
export interface StatusResponse {
  /** Whether an LLM backend is configured. */
  ai_mode: boolean;
  /** Whether a HubSpot access token is configured. */
  hubspot_configured: boolean;
}

/**
 * A single HubSpot list entry as returned by
 * `GET /api/audience-builder/lists/search`
 * (see services/backend/internal/domain/model/hubspot.go ListInfo).
 */
export interface AudienceListInfo {
  id: string;
  name: string;
  size: number;
  processingType?: string;
}

/** Response body for `GET /api/audience-builder/lists/search`. */
export interface ListsSearchResponse {
  query: string;
  results: AudienceListInfo[];
}

/**
 * A standard hygiene suppression/opt-out list resolved by name search
 * (see services/backend/internal/domain/model/audience.go SuppressionList).
 */
export interface SuppressionList {
  key: string;
  label: string;
  list_id: string;
  name: string;
  size?: number;
  category: 'standard' | 'brand' | 'event_specific';
}

/** Response body for `GET /api/audience-builder/suppression-lists`. */
export interface SuppressionListsResponse {
  results: SuppressionList[];
}

/** A previously-built master list for this event, surfaced for reuse. */
export interface ExistingMasterList {
  list_id: string;
  name: string;
  size?: number;
  hubspot_url: string;
}

/** Response body for `GET /api/audience-builder/existing-master-lists`. */
export interface ExistingMasterListsResponse {
  results: ExistingMasterList[];
}

/** A list ID resolved to display info (last-sent included/suppression lists). */
export interface ListBrief {
  list_id: string;
  name: string;
  size?: number;
  missing?: boolean;
  resolved_from_legacy_id?: string;
}

/** One previously-sent marketing email for an event. */
export interface LastSentEmail {
  email_id: string;
  email_name: string;
  sent_at: string;
  hubspot_url: string;
  included_lists: ListBrief[];
  suppression_lists: ListBrief[];
}

/** Response body for `GET /api/audience-builder/last-sent`. */
export interface LastSentResponse {
  results: LastSentEmail[];
}

/** Request body for `POST /api/audience-builder/preview-count`. */
export interface PreviewCountRequest {
  list_ids: string[];
}

/** Response body for `POST /api/audience-builder/preview-count`. */
export interface PreviewCountResponse {
  exact: boolean;
  estimate: number;
  count: number;
  reason?: string;
}

/** Request body for `POST /api/audience-builder/compose-master`. */
export interface ComposeMasterListRequest {
  list_ids: string[];
  name?: string;
  event_url?: string;
  brand_short?: string;
  event_name?: string;
  exclude_list_ids?: string[];
}

/** Response body for `POST /api/audience-builder/compose-master`. */
export interface ComposeMasterListResponse {
  list_id: string;
  name: string;
  hubspot_url: string;
  size: string;
  source_list_ids: string[];
  suppression_list_id?: string;
  suppression_name?: string;
  suppression_hubspot_url?: string;
  suppression_size?: string;
}

/** Request body for `POST /api/audience-builder/qa/run`. */
export interface QaRunRequest {
  list_ref: string;
  targets_eu?: boolean;
  targets_ca?: boolean;
}

/** One issue surfaced by a QA check. */
export interface QaFinding {
  severity: string;
  message: string;
  fix: string;
}

/** The outcome of one QA check. */
export interface QaCheckResult {
  verdict: string;
  findings: QaFinding[];
  applied?: { gdpr: boolean; opt_out: boolean };
  exclusion_count?: number;
}

/** Response body for `POST /api/audience-builder/qa/run` when disambiguation is needed. */
export interface QaDisambiguationResponse {
  needs_disambiguation: true;
  candidates: { list_id: string; name: string; size?: number }[];
}

/** Response body for `POST /api/audience-builder/qa/run` on success. */
export interface QaResultResponse {
  needs_disambiguation: false;
  list_id: string;
  name: string;
  hubspot_url: string;
  checks: Record<string, QaCheckResult>;
  findings: QaFinding[];
  overall: string;
}

export type QaRunResponse = QaDisambiguationResponse | QaResultResponse;

// ─── Email-creation wizard (legacy Python backend, proxied at /api/*
// excluding /api/audience-builder/* and /api/status — see main.py) ───

/** Request body for `POST /api/plan-start`. */
export interface PlanStartRequest {
  url: string;
  extra_context?: string;
  email_type?: string;
  is_transactional?: boolean;
  progress_token: string;
}

/** Response body for `POST /api/plan-start`. */
export interface PlanStartResponse {
  token: string;
}

/** One event surfaced over `GET /api/progress/{token}` (SSE, `data:` payload). */
export type ProgressEvent =
  | { type: 'heartbeat' }
  | { type: 'brief'; text: string; error?: boolean; done?: boolean }
  | { type: 'plan_done'; result: PlanResult }
  | { type: 'error'; text: string };

/** The `result` field of a `plan_done` progress event. */
export interface PlanResult {
  session_id: string;
  message: string;
  phase: string;
  mode: string;
  source_email: { id: string; name: string } | null;
  stage: Record<string, unknown>;
  utm: Record<string, string>;
}

/** Request body for `POST /api/generate-content`. */
export interface GenerateContentRequest {
  session_id: string;
  change_request?: string;
  progress_token?: string;
}

/** One content block in an email body — reordered/removed by the user in step 2. */
export interface ContentSection {
  type: string;
  html?: string;
  text?: string;
  [key: string]: unknown;
}

/** Response body for `POST /api/generate-content`. */
export interface GenerateContentResponse {
  session_id: string;
  generated_subject: string;
  generated_preview: string;
  generated_html: string;
  sections: ContentSection[];
  banner_url: string;
  variant_a_subject: string;
  variant_a_preview: string;
  variant_a_html: string;
  variant_a_template_key: string;
  variant_a_mode: string;
}

/** Request body for `POST /api/update-sections`. */
export interface UpdateSectionsRequest {
  session_id: string;
  sections: ContentSection[];
}

/** Response body for `POST /api/update-sections`. */
export interface UpdateSectionsResponse {
  session_id: string;
  generated_html: string;
  sections_count: number;
}

/** Request body for `POST /api/clone`. */
export interface CloneRequest {
  session_id: string;
  approved: boolean;
  subject?: string;
  preview_text?: string;
  send_list_id?: string;
}

/** Response body for `POST /api/clone`. */
export interface CloneResponse {
  session_id: string;
  message: string;
  phase: string;
  email_id?: string;
  draft_url?: string;
  content_applied?: boolean;
  validation_passed?: boolean;
  validation_issues?: string[];
  variant_a_email_id?: string;
  variant_a_draft_url?: string;
  variant_b_email_id?: string;
  variant_b_draft_url?: string;
}

/** Request body for `POST /api/set-send-list`. */
export interface SetSendListRequest {
  session_id?: string;
  email_id?: string;
  send_list_id?: string;
  send_list_ids?: string[];
  suppression_list_ids?: string[];
}

/** Response body for `POST /api/set-send-list`. */
export interface SetSendListResponse {
  email_id: string;
  send_list_id: string;
  list_type?: string;
  success: boolean;
  to?: unknown;
}

/** Request body for `POST /api/chat`. */
export interface ChatRequest {
  session_id: string;
  message: string;
}

/** Response body for `POST /api/chat`. */
export interface ChatResponse {
  session_id: string;
  message: string;
  phase: string;
  draft_url?: string;
}

// ─── Audience Preview (Step 3) plan/build flows — session-scoped
// (`/api/audience-plan`, `/api/build-audience`) and standalone
// (`/api/audience/plan`, `/api/audience/run`, `/api/audience/custom-plan`,
// `/api/audience/custom-run`) variants, streamed via
// `/api/audience-stream/{job_id}` (see main.py stream_audience_build) ───

/** Request body for `POST /api/audience-plan` (or `/api/audience/plan` when session_id is omitted). */
export interface AudiencePlanRequest {
  session_id?: string;
  event_url: string;
  /** Accumulated "Q: ...\nA: ..." text from answered clarifying questions (see AudienceQuestion). */
  qa?: string;
}

/** Request body for `POST /api/build-audience` (or `/api/audience/run` when session_id is omitted). */
export interface BuildAudienceRequest {
  session_id?: string;
  event_url: string;
  plan: string;
  qa?: string;
}

/** Request body for `POST /api/audience/custom-plan`. */
export interface CustomAudiencePlanRequest {
  request: string;
  qa?: string;
}

/** Request body for `POST /api/audience/custom-run`. */
export interface CustomAudienceRunRequest {
  request: string;
  plan: string;
  qa?: string;
}

/** Response body shared by all audience plan/build start routes. */
export interface AudienceJobResponse {
  job_id: string;
  event_url?: string;
}

/**
 * One disambiguation/clarifying question surfaced by the planning agent's
 * `present_open_questions` tool call (see backend/audience_tools.py).
 */
export interface AudienceQuestion {
  question: string;
  why_it_blocks?: string;
  options: string[];
  /** Whether a free-text "Other" answer is allowed (defaults true when omitted). */
  allow_custom?: boolean;
}

/** One event surfaced over `GET /api/audience-stream/{job_id}` (SSE, `data:` payload). */
export type AudienceStreamEvent =
  | { type: 'heartbeat' }
  | { type: 'output'; text: string; delta?: boolean }
  | { type: 'question'; questions: AudienceQuestion[] }
  | {
      type: 'complete';
      done: true;
      master_list_id?: string;
      master_list_url?: string;
      suppression_lists?: SuppressionList[];
      posthoc_applied?: boolean;
      success?: boolean;
    }
  | { type: 'error'; text: string };
