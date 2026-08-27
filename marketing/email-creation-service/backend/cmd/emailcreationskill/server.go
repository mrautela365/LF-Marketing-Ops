package main

import (
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	statusserver "github.com/linuxfoundation/lfx-v2-emailcreation-service/gen/http/status/server"
	statusgen "github.com/linuxfoundation/lfx-v2-emailcreation-service/gen/status"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/dispatch"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/infrastructure/config"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/infrastructure/memory"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/infrastructure/sse"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/audiencetools"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/discovery"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/service/wizardagent"
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
	r.Use(middleware.Logger)

	s := &Server{router: r, cfg: cfg}
	mountStatusService(r, cfg)

	hubspot := dispatch.NewHubSpotClient(cfg.HubSpotAccessToken, cfg.HubSpotPortalID, cfg.AssetTag)
	s.mountAudienceBuilderRoutes(hubspot, hubspot, cfg.HubSpotPortalID)

	// --- Wizard agent wiring ---
	sessions := memory.NewSessionStore()
	broker := sse.NewBroker()
	scraper := dispatch.NewWebScraper(cfg.GoogleServiceAccountFile)
	selected := dispatch.SelectLLMBackend(cfg)

	agent := wizardagent.New(hubspot, hubspot, selected.Gateway, scraper, cfg.HubSpotPortalID)
	agent.CLI = selected.CLISkillRunner
	agent.AnthropicAPIKeySet = cfg.AnthropicAPIKey != ""

	s.mountWizardRoutes(sessions, broker, agent, selected.ModeName, cfg.HubSpotPortalID)
	s.mountStageFromBriefRoutes(agent, cfg.HubSpotPortalID, cfg.InternalAPIToken)

	// --- Audience-builder agentic layer (audience_tools.py / audience_builder/*) ---
	var sfClient domain.SnowflakeClient
	if cfg.SnowflakeAccount != "" {
		sfClient = dispatch.NewSnowflakeClient(
			cfg.SnowflakeAccount, cfg.SnowflakeUser, cfg.SnowflakePrivateKey,
			cfg.SnowflakeDatabase, cfg.SnowflakeSchema, cfg.SnowflakeWarehouse, cfg.SnowflakeRole,
		)
	}
	audienceToolkit := audiencetools.NewToolkit(hubspot, hubspot, sfClient, cfg.HubSpotPortalID)
	audienceSvc := audiencetools.NewService(audienceToolkit, selected.Gateway)
	discoverySvc := discovery.NewService(audienceToolkit, selected.Gateway)

	s.mountAudienceJobRoutes(sessions, audienceSvc, agent, cfg, cfg.HubSpotPortalID)
	s.mountDiscoveryRoutes(discoverySvc)

	var asanaClient domain.AsanaClient
	if cfg.AsanaAccessToken != "" {
		asanaClient = dispatch.NewAsanaClient(cfg.AsanaAccessToken)
	}
	s.mountAsanaPlanRoutes(agent, asanaClient)

	// The SPA catch-all must be mounted last so its wildcard route never
	// shadows the API routes registered above.
	s.mountSPARoutes(cfg.FrontendDir)

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
