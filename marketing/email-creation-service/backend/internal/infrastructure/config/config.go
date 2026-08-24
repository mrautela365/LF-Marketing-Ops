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
		repoRoot + string(os.PathSeparator) + ".." + string(os.PathSeparator) + "survey_workflow" + string(os.PathSeparator) + ".env",
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

// findRepoRoot looks for the monorepo root .env file. This service lives
// at marketing/email-creation-service/backend, not inside
// marketing/emailcreationskill/ (where the .env actually is), so a plain
// upward walk won't find it — check each ancestor directory itself and its
// "emailcreationskill" sibling. Falls back to start itself if no .env is
// found within a few levels.
func findRepoRoot(start string) string {
	dir := start
	for i := 0; i < 5; i++ {
		if _, err := os.Stat(dir + string(os.PathSeparator) + ".env"); err == nil {
			return dir
		}
		sibling := filepath.Join(dir, "emailcreationskill")
		if _, err := os.Stat(sibling + string(os.PathSeparator) + ".env"); err == nil {
			return sibling
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
