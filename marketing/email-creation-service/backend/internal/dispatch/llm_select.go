// llm_select.go picks one domain.LLMGateway backend at startup, mirroring
// llm/gateway.py's backend_name()/get_backend() priority exactly: Anthropic
// API key present > LiteLLM configured > CLI fallback. In this deployment
// neither of the first two is ever configured with a valid value, so the
// CLI backend is always what actually runs — but the priority order itself
// must still match Python's so status reporting and any future config
// change behave identically.
package dispatch

import (
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/infrastructure/config"
)

// SelectedBackend bundles the chosen domain.LLMGateway with a human-readable
// mode string mirroring Python's status descriptions ("Claude AI (Anthropic
// API)" / "Claude AI (LiteLLM — {url})" / "Claude AI (Claude Code)") and the
// CLI-only skill runner (fetch_asana_task_via_mcp is CLI-only regardless of
// which backend is selected for RunAgent/CompleteText).
type SelectedBackend struct {
	Gateway        domain.LLMGateway
	ModeName       string
	CLISkillRunner domain.CLISkillRunner
}

// SelectLLMBackend mirrors backend_name()'s exact priority order.
func SelectLLMBackend(cfg *config.Config) SelectedBackend {
	cli := NewClaudeCLIGateway(cfg.ClaudeModel)
	cli.CLIPath = cfg.ClaudeCLIPath

	switch {
	case cfg.AnthropicAPIKey != "":
		return SelectedBackend{
			Gateway:        NewAnthropicSDKGateway(cfg.AnthropicAPIKey, cfg.ClaudeModel),
			ModeName:       "Claude AI (Anthropic API)",
			CLISkillRunner: cli,
		}
	case cfg.LiteLLMBaseURL != "":
		return SelectedBackend{
			Gateway:        NewLiteLLMGateway(cfg.LiteLLMBaseURL, cfg.LiteLLMAPIKey, cfg.ClaudeModel),
			ModeName:       "Claude AI (LiteLLM — " + cfg.LiteLLMBaseURL + ")",
			CLISkillRunner: cli,
		}
	default:
		return SelectedBackend{
			Gateway:        cli,
			ModeName:       "Claude AI (Claude Code)",
			CLISkillRunner: cli,
		}
	}
}
