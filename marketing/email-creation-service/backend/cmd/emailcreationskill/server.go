package main

import (
	"net/http"

	"github.com/go-chi/chi/v5"
	statusserver "github.com/linuxfoundation/lfx-v2-emailcreation-service/gen/http/status/server"
	statusgen "github.com/linuxfoundation/lfx-v2-emailcreation-service/gen/status"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/dispatch"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/infrastructure/config"
	goahttp "goa.design/goa/v3/http"
)

// Server wraps the HTTP router. Route registration grows phase by phase
// (see the migration plan) — today it only exposes a health check.
type Server struct {
	router *chi.Mux
	cfg    *config.Config
}

// NewServer builds the router and mounts every route group. Handlers are
// added incrementally in later migration phases via container/bootstrap
// wiring; for now this only proves the skeleton boots.
func NewServer(cfg *config.Config) *Server {
	r := chi.NewRouter()

	s := &Server{router: r, cfg: cfg}
	mountStatusService(r, cfg)

	hubspot := dispatch.NewHubSpotClient(cfg.HubSpotAccessToken, cfg.HubSpotPortalID, cfg.AssetTag)
	s.mountAudienceBuilderRoutes(hubspot, hubspot, cfg.HubSpotPortalID)
	// Future SSE endpoints (discovery-stream, job progress) mount directly
	// on r here too — Goa's generated transport doesn't fit long-lived
	// streams, so they stay outside the design/ contract.

	return s
}

func (s *Server) ListenAndServe(addr string) error {
	return http.ListenAndServe(addr, s.router)
}

// mountStatusService wires the Goa-generated status service onto a
// dedicated goa mux and mounts that mux on the chi router at the exact
// path the design declares. This is the first endpoint on the design-first
// Goa path (see design/design.go); every other route is still directly
// chi-mounted pending a later migration pass.
func mountStatusService(r *chi.Mux, cfg *config.Config) {
	svc := &statusService{cfg: cfg}
	endpoints := statusgen.NewEndpoints(svc)

	goaMux := goahttp.NewMuxer()
	srv := statusserver.New(endpoints, goaMux, goahttp.RequestDecoder, goahttp.ResponseEncoder, nil, nil)
	srv.Mount(goaMux)

	r.Handle("/api/status", goaMux)
}
