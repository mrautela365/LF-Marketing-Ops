package main

import (
	"context"

	statusgen "github.com/linuxfoundation/lfx-v2-emailcreation-service/gen/status"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/infrastructure/config"
)

// statusService implements the Goa-generated status.Service interface —
// the first endpoint migrated onto the design-first Goa path (see
// design/design.go). Every other route is still chi-mounted pending a
// later migration pass.
type statusService struct {
	cfg *config.Config
}

func (s *statusService) Get(context.Context) (*statusgen.StatusResult, error) {
	return &statusgen.StatusResult{
		AiMode:            s.cfg.AnthropicAPIKey != "" || s.cfg.LiteLLMBaseURL != "",
		HubspotConfigured: s.cfg.HubSpotAccessToken != "",
	}, nil
}
