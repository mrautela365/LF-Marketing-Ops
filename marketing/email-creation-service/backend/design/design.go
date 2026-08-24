// Package design holds the Goa API design (contract-first, per
// lfx-v2-campaign-service's convention). Run `make apigen` after editing
// this file to regenerate internal/gen/.
//
// Only endpoints with plain request/response semantics belong here.
// Streaming (SSE) endpoints are intentionally NOT modeled in Goa — its
// generated HTTP transport doesn't fit long-lived event streams well — and
// are instead mounted directly on the chi router in cmd/emailcreationskill
// (see server.go). The audience-builder routes are still chi-mounted too,
// pending a later migration pass into this design; status is the first
// slice proving the Goa-generated path end to end.
package design

import (
	. "goa.design/goa/v3/dsl"
)

var _ = API("emailcreationskill", func() {
	Title("LFX Email Creation Service")
	Description("Marketing email planning, cloning, and audience-list tooling for HubSpot.")
	Server("emailcreationskill", func() {
		Host("localhost", func() {
			URI("http://localhost:8000")
		})
	})
})

var _ = Service("status", func() {
	Description("Service health/status.")
	HTTP(func() {
		Path("/api/status")
	})

	Method("get", func() {
		Result(StatusResult)
		HTTP(func() {
			GET("/")
		})
	})
})

var StatusResult = Type("StatusResult", func() {
	Attribute("ai_mode", Boolean, "Whether an LLM backend is configured.")
	Attribute("hubspot_configured", Boolean, "Whether a HubSpot access token is configured.")
	Required("ai_mode", "hubspot_configured")
})
