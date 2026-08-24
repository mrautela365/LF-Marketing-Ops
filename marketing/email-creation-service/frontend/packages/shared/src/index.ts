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
