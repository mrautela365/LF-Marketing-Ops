// llm_anthropic_sdk.go ports llm/gateway.py's direct-Anthropic-API path
// (_agent_sdk / the SDK branch of complete_text), selected by llm_select.go
// only when ANTHROPIC_API_KEY is present in the literal .env file (per
// config.Load's doc comment, never from the ambient process environment).
// This backend is never exercised in the current deployment since no valid
// key is configured, but is implemented for source parity with Python's
// three-tier backend priority.
package dispatch

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
)

const anthropicAPIURL = "https://api.anthropic.com/v1/messages"
const anthropicAPIVersion = "2023-06-01"

// AnthropicSDKGateway implements domain.LLMGateway and domain.CLISkillRunner
// (the latter by delegating to a CLI gateway, since a direct API session has
// no CLI-native MCP tool integrations — mirrors run_cli_skill being CLI-only
// regardless of the configured backend) via the Anthropic Messages API.
type AnthropicSDKGateway struct {
	APIKey string
	Model  string
	Client *http.Client
}

// NewAnthropicSDKGateway builds a gateway targeting the given model id.
func NewAnthropicSDKGateway(apiKey, model string) *AnthropicSDKGateway {
	return &AnthropicSDKGateway{APIKey: apiKey, Model: model, Client: &http.Client{Timeout: 0}}
}

type anthropicContentBlock struct {
	Type  string         `json:"type"`
	Text  string         `json:"text,omitempty"`
	ID    string         `json:"id,omitempty"`
	Name  string         `json:"name,omitempty"`
	Input map[string]any `json:"input,omitempty"`

	ToolUseID string `json:"tool_use_id,omitempty"`
	Content   string `json:"content,omitempty"`
}

type anthropicMessage struct {
	Role    string                  `json:"role"`
	Content []anthropicContentBlock `json:"content"`
}

type anthropicToolDef struct {
	Name        string         `json:"name"`
	Description string         `json:"description"`
	InputSchema map[string]any `json:"input_schema"`
}

type anthropicRequest struct {
	Model       string             `json:"model"`
	MaxTokens   int                `json:"max_tokens"`
	Temperature float64            `json:"temperature"`
	System      string             `json:"system,omitempty"`
	Messages    []anthropicMessage `json:"messages"`
	Tools       []anthropicToolDef `json:"tools,omitempty"`
}

type anthropicResponse struct {
	Content    []anthropicContentBlock `json:"content"`
	StopReason string                  `json:"stop_reason"`
	Error      *struct {
		Type    string `json:"type"`
		Message string `json:"message"`
	} `json:"error"`
}

func (g *AnthropicSDKGateway) doRequest(ctx context.Context, req anthropicRequest, timeoutSeconds int) (*anthropicResponse, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, err
	}
	if timeoutSeconds <= 0 {
		timeoutSeconds = 120
	}
	callCtx, cancel := context.WithTimeout(ctx, time.Duration(timeoutSeconds)*time.Second)
	defer cancel()

	httpReq, err := http.NewRequestWithContext(callCtx, http.MethodPost, anthropicAPIURL, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	httpReq.Header.Set("content-type", "application/json")
	httpReq.Header.Set("x-api-key", g.APIKey)
	httpReq.Header.Set("anthropic-version", anthropicAPIVersion)

	resp, err := g.Client.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("anthropic API request: %w", err)
	}
	defer resp.Body.Close()
	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	var parsed anthropicResponse
	if err := json.Unmarshal(respBody, &parsed); err != nil {
		return nil, fmt.Errorf("anthropic API response decode: %w (body: %s)", err, string(respBody))
	}
	if parsed.Error != nil {
		return nil, fmt.Errorf("anthropic API error (%s): %s", parsed.Error.Type, parsed.Error.Message)
	}
	return &parsed, nil
}

// CompleteText implements domain.LLMGateway, mirroring complete_text's SDK
// branch: a direct, non-streaming Messages API call with temperature=0.0
// pinned (matching llm/gateway.py's TEMPERATURE constant across all
// backends).
func (g *AnthropicSDKGateway) CompleteText(ctx context.Context, prompt string, opts domain.CompleteTextOptions) (string, error) {
	maxTokens := opts.MaxTokens
	if maxTokens <= 0 {
		maxTokens = 1024
	}
	req := anthropicRequest{
		Model:       g.Model,
		MaxTokens:   maxTokens,
		Temperature: 0.0,
		System:      opts.System,
		Messages: []anthropicMessage{
			{Role: "user", Content: []anthropicContentBlock{{Type: "text", Text: prompt}}},
		},
	}
	timeout := opts.TimeoutSeconds
	resp, err := g.doRequest(ctx, req, timeout)
	if err != nil {
		return "", err
	}
	return concatText(resp.Content), nil
}

func concatText(blocks []anthropicContentBlock) string {
	var sb strings.Builder
	for _, b := range blocks {
		if b.Type == "text" {
			sb.WriteString(b.Text)
		}
	}
	return strings.TrimSpace(sb.String())
}

func toAnthropicTools(tools []domain.ToolDef) []anthropicToolDef {
	out := make([]anthropicToolDef, 0, len(tools))
	for _, t := range tools {
		out = append(out, anthropicToolDef{Name: t.Name, Description: t.Description, InputSchema: t.InputSchema})
	}
	return out
}

// RunAgent implements domain.LLMGateway, mirroring _agent_sdk: a native
// multi-turn tool-calling loop over the Messages API (unlike the CLI
// backend's TOOL_CALL:/TOOL_RESULT: text-protocol emulation, tool_use/
// tool_result content blocks are used directly), with the same best_plan
// fallback heuristic as the CLI backend for a turn that never reaches a
// clean final answer within MaxSteps.
func (g *AnthropicSDKGateway) RunAgent(ctx context.Context, messages []domain.Message, system string, tools []domain.ToolDef, executeTool domain.ExecuteToolFunc, opts domain.RunAgentOptions) (string, []domain.Message, error) {
	maxSteps := opts.MaxSteps
	if maxSteps <= 0 {
		maxSteps = 8
	}
	maxTokens := opts.MaxTokens
	if maxTokens <= 0 {
		maxTokens = 4096
	}

	convo := make([]anthropicMessage, 0, len(messages))
	for _, m := range messages {
		convo = append(convo, anthropicMessage{Role: m.Role, Content: []anthropicContentBlock{{Type: "text", Text: m.Content}}})
	}

	anthropicTools := toAnthropicTools(tools)
	var bestPlan, finalText string
	ranOutOfSteps := true

	for i := 0; i < maxSteps; i++ {
		req := anthropicRequest{
			Model:       g.Model,
			MaxTokens:   maxTokens,
			Temperature: 0.0,
			System:      system,
			Messages:    convo,
			Tools:       anthropicTools,
		}
		resp, err := g.doRequest(ctx, req, 300)
		if err != nil {
			return "", messages, err
		}

		text := concatText(resp.Content)
		if looksLikePlan(text) && len(text) > len(bestPlan) {
			bestPlan = text
		}

		var toolUses []anthropicContentBlock
		for _, b := range resp.Content {
			if b.Type == "tool_use" {
				toolUses = append(toolUses, b)
				emitEvent(opts.OnEvent, domain.AgentEvent{Type: "tool", Name: b.Name, Input: b.Input})
			}
		}
		if text != "" {
			emitEvent(opts.OnEvent, domain.AgentEvent{Type: "output", Text: text})
		}

		if len(toolUses) == 0 || resp.StopReason != "tool_use" {
			if looksLikePlan(text) {
				finalText = text
			} else if bestPlan != "" {
				finalText = bestPlan
			} else {
				finalText = text
			}
			ranOutOfSteps = false
			break
		}

		convo = append(convo, anthropicMessage{Role: "assistant", Content: resp.Content})
		var toolResults []anthropicContentBlock
		for _, tu := range toolUses {
			result := executeTool(tu.Name, tu.Input)
			truncated := result
			if len(truncated) > 200 {
				truncated = truncated[:200]
			}
			emitEvent(opts.OnEvent, domain.AgentEvent{Type: "tool_result", Text: truncated})
			toolResults = append(toolResults, anthropicContentBlock{Type: "tool_result", ToolUseID: tu.ID, Content: result})
		}
		convo = append(convo, anthropicMessage{Role: "user", Content: toolResults})
	}
	if ranOutOfSteps {
		finalText = bestPlan
	}

	updated := append(append([]domain.Message{}, messages...), domain.Message{Role: "assistant", Content: finalText})
	return finalText, updated, nil
}
