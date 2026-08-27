// Package config centralizes all environment-driven configuration. Every
// env var the service reads must be declared here — no os.Getenv calls
// scattered through service/dispatch code (unlike the Python original,
// which read Snowflake credentials directly in audience_tools.py).
package config

import (
	"os"
	"path/filepath"
	"strings"

	"github.com/joho/godotenv"
)

// Config holds every environment-derived setting used by the service.
type Config struct {
	AnthropicAPIKey string
	ClaudeModel     string
	// ClaudeCLIPath overrides the `claude` CLI binary lookup used by
	// dispatch/llm_claude_cli.go. Empty means PATH lookup / hardcoded
	// fallback (mirrors Python's _cli_path()).
	ClaudeCLIPath string

	HubSpotAccessToken string
	HubSpotPortalID    string

	GoogleServiceAccountFile string

	// InternalAPIToken gates POST /api/stage-from-brief. Empty means the
	// endpoint accepts calls unauthenticated (local dev only) — mirrors
	// the Python behavior, not a new relaxation.
	InternalAPIToken string

	AsanaAccessToken string

	// FrontendDir is the directory of static SPA assets served by the
	// catch-all route (index.html + hashed bundle files), mirroring
	// Python's FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..",
	// "frontend"). This Go service's frontend (marketing/email-creation-
	// service/frontend) is an unbuilt Angular monorepo app with no plain
	// static dist/ directory checked in, so there is no exact equivalent to
	// point at yet; this defaults to an expected build output directory and
	// the SPA handler no-ops (falls through to chi's default 404) when the
	// directory doesn't exist, rather than failing server startup.
	FrontendDir string

	// AssetTag, if set, is appended to the name of every HubSpot asset this
	// service creates (cloned emails, audience/suppression lists), e.g.
	// AssetTag=psh-test -> "... [psh-test]". Leave empty in prod.
	AssetTag string

	// LiteLLM proxy config. Takes priority over AnthropicAPIKey when both
	// are set (selection logic lives in the LLM gateway adapters, not here).
	LiteLLMBaseURL string
	LiteLLMAPIKey  string

	// Snowflake credentials, used by dispatch/snowflake.go.
	SnowflakeAccount    string
	SnowflakeUser       string
	SnowflakePrivateKey string // PEM
	SnowflakeDatabase   string
	SnowflakeSchema     string
	SnowflakeWarehouse  string
	SnowflakeRole       string
}

// Load reads .env (with an optional sibling survey_workflow/.env override,
// matching the precedence the Python service relies on) and process env
// vars into a Config. Values explicitly set in a .env file take priority
// for AnthropicAPIKey specifically, because Claude Code injects its own
// session-scoped ANTHROPIC_API_KEY into the process environment that is
// NOT valid for direct Anthropic API calls — only a key explicitly written
// to a .env file should be trusted for that field.
func Load(projectRoot string) (*Config, error) {
	repoRoot := findRepoRoot(projectRoot)
	envPaths := []string{
		repoRoot + string(os.PathSeparator) + ".env",
		// marketing/survey_workflow/.env, a sibling project's secrets file
		// this service also honors — repoRoot is marketing/email-creation-
		// service/backend, so survey_workflow lives two levels up.
		filepath.Join(repoRoot, "..", "..", "survey_workflow", ".env"),
	}

	fileValues := map[string]string{}
	for _, p := range envPaths {
		if _, err := os.Stat(p); err != nil {
			continue
		}
		vals, err := godotenv.Read(p)
		if err != nil {
			return nil, err
		}
		if err := godotenv.Overload(p); err != nil {
			return nil, err
		}
		for k, v := range vals {
			fileValues[k] = v // later paths win, same as Python's dict.update loop
		}
	}

	cfg := &Config{
		AnthropicAPIKey:          fileValues["ANTHROPIC_API_KEY"],
		ClaudeModel:              envOr("CLAUDE_MODEL", "claude-sonnet-4-6"),
		ClaudeCLIPath:            envOr("CLAUDE_CLI_PATH", ""),
		HubSpotAccessToken:       envOr("HUBSPOT_ACCESS_TOKEN", ""),
		HubSpotPortalID:          envOr("HUBSPOT_PORTAL_ID", "8112310"),
		GoogleServiceAccountFile: envOr("GOOGLE_SERVICE_ACCOUNT_FILE", ""),
		InternalAPIToken:         envOr("INTERNAL_API_TOKEN", ""),
		AsanaAccessToken:         envOr("ASANA_ACCESS_TOKEN", ""),
		FrontendDir:              envOr("FRONTEND_DIR", filepath.Join(repoRoot, "..", "frontend", "apps", "email-creation-ui", "dist")),
		AssetTag:                 strings.TrimSpace(envOr("ASSET_TAG", "")),
		LiteLLMBaseURL:           envOr("LITELLM_BASE_URL", ""),
		LiteLLMAPIKey:            envOr("LITELLM_API_KEY", ""),
		SnowflakeAccount:         envOr("SNOWFLAKE_ACCOUNT", ""),
		SnowflakeUser:            envOr("SNOWFLAKE_USER", ""),
		SnowflakePrivateKey:      envOr("SNOWFLAKE_PRIVATE_KEY", ""),
		SnowflakeDatabase:        envOr("SNOWFLAKE_DATABASE", "ANALYTICS"),
		SnowflakeSchema:          envOr("SNOWFLAKE_SCHEMA", "Silver_Segment"),
		SnowflakeWarehouse:       envOr("SNOWFLAKE_WAREHOUSE", ""),
		SnowflakeRole:            envOr("SNOWFLAKE_ROLE", ""),
	}
	return cfg, nil
}

// TagAssetName appends AssetTag to a HubSpot asset name. No-op when
// AssetTag is unset or name is empty.
func (c *Config) TagAssetName(name string) string {
	if c.AssetTag == "" || name == "" {
		return name
	}
	suffix := " [" + c.AssetTag + "]"
	if strings.HasSuffix(name, suffix) {
		return name
	}
	return name + suffix
}

// findRepoRoot walks up from start looking for a directory containing
// .env, stopping at the filesystem root. Falls back to start itself if
// none is found within a few levels.
func findRepoRoot(start string) string {
	dir := start
	for i := 0; i < 5; i++ {
		if _, err := os.Stat(dir + string(os.PathSeparator) + ".env"); err == nil {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	return start
}

func envOr(key, fallback string) string {
	if v, ok := os.LookupEnv(key); ok {
		return v
	}
	return fallback
}
