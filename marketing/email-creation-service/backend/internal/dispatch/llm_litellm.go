// llm_litellm.go ports llm/gateway.py's LiteLLM path (the middle tier of
// backend_name()'s priority: used when LITELLM_BASE_URL is configured but no
// Anthropic API key is present), talking to an OpenAI-compatible
// chat/completions endpoint. Never exercised in the current deployment
// (LiteLLM is not configured), implemented for source parity only.
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

// LiteLLMGateway implements domain.LLMGateway via an OpenAI-compatible
// chat/completions endpoint fronted by LiteLLM.
type LiteLLMGateway struct {
	BaseURL string
	APIKey  string
	Model   string
	Client  *http.Client
}

// NewLiteLLMGateway builds a gateway against baseURL (LITELLM_BASE_URL).
func NewLiteLLMGateway(baseURL, apiKey, model string) *LiteLLMGateway {
	return &LiteLLMGateway{BaseURL: strings.TrimRight(baseURL, "/"), APIKey: apiKey, Model: model, Client: &http.Client{Timeout: 0}}
}

type openAIFunctionDef struct {
	Name        string         `json:"name"`
	Description string         `json:"description"`
	Parameters  map[string]any `json:"parameters"`
}

type openAITool struct {
	Type     string            `json:"type"`
	Function openAIFunctionDef `json:"function"`
}

type openAIToolCall struct {
	ID       string `json:"id"`
	Type     string `json:"type"`
	Function struct {
		Name      string `json:"name"`
		Arguments string `json:"arguments"`
	} `json:"function"`
}

type openAIMessage struct {
	Role       string           `json:"role"`
	Content    string           `json:"content,omitempty"`
	ToolCalls  []openAIToolCall `json:"tool_calls,omitempty"`
	ToolCallID string           `json:"tool_call_id,omitempty"`
	Name       string           `json:"name,omitempty"`
}

type openAIChatRequest struct {
	Model       string          `json:"model"`
	Messages    []openAIMessage `json:"messages"`
	Temperature float64         `json:"temperature"`
	MaxTokens   int             `json:"max_tokens,omitempty"`
	Tools       []openAITool    `json:"tools,omitempty"`
}

type openAIChatResponse struct {
	Choices []struct {
		Message      openAIMessage `json:"message"`
		FinishReason string        `json:"finish_reason"`
	} `json:"choices"`
	Error *struct {
		Message string `json:"message"`
	} `json:"error"`
}

func (g *LiteLLMGateway) doRequest(ctx context.Context, req openAIChatRequest, timeoutSeconds int) (*openAIChatResponse, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, err
	}
	if timeoutSeconds <= 0 {
		timeoutSeconds = 120
	}
	callCtx, cancel := context.WithTimeout(ctx, time.Duration(timeoutSeconds)*time.Second)
	defer cancel()

	httpReq, err := http.NewRequestWithContext(callCtx, http.MethodPost, g.BaseURL+"/chat/completions", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	httpReq.Header.Set("content-type", "application/json")
	if g.APIKey != "" {
		httpReq.Header.Set("authorization", "Bearer "+g.APIKey)
	}

	resp, err := g.Client.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("litellm request: %w", err)
	}
	defer resp.Body.Close()
	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	var parsed openAIChatResponse
	if err := json.Unmarshal(respBody, &parsed); err != nil {
		return nil, fmt.Errorf("litellm response decode: %w (body: %s)", err, string(respBody))
	}
	if parsed.Error != nil {
		return nil, fmt.Errorf("litellm error: %s", parsed.Error.Message)
	}
	if len(parsed.Choices) == 0 {
		return nil, fmt.Errorf("litellm response had no choices (body: %s)", string(respBody))
	}
	return &parsed, nil
}

// CompleteText implements domain.LLMGateway, mirroring complete_text's
// LiteLLM branch: a single-shot chat/completions call, temperature=0.0.
func (g *LiteLLMGateway) CompleteText(ctx context.Context, prompt string, opts domain.CompleteTextOptions) (string, error) {
	var messages []openAIMessage
	if opts.System != "" {
		messages = append(messages, openAIMessage{Role: "system", Content: opts.System})
	}
	messages = append(messages, openAIMessage{Role: "user", Content: prompt})

	req := openAIChatRequest{
		Model:       g.Model,
		Messages:    messages,
		Temperature: 0.0,
		MaxTokens:   opts.MaxTokens,
	}
	resp, err := g.doRequest(ctx, req, opts.TimeoutSeconds)
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(resp.Choices[0].Message.Content), nil
}

func toOpenAITools(tools []domain.ToolDef) []openAITool {
	out := make([]openAITool, 0, len(tools))
	for _, t := range tools {
		out = append(out, openAITool{
			Type: "function",
			Function: openAIFunctionDef{
				Name:        t.Name,
				Description: t.Description,
				Parameters:  t.InputSchema,
			},
		})
	}
	return out
}

// RunAgent implements domain.LLMGateway, mirroring the LiteLLM branch of the
// agent loop: OpenAI-shaped tool_calls in the response, tool results fed
// back as role="tool" messages, with the same best_plan fallback heuristic
// as the other two backends.
func (g *LiteLLMGateway) RunAgent(ctx context.Context, messages []domain.Message, system string, tools []domain.ToolDef, executeTool domain.ExecuteToolFunc, opts domain.RunAgentOptions) (string, []domain.Message, error) {
	maxSteps := opts.MaxSteps
	if maxSteps <= 0 {
		maxSteps = 8
	}
	maxTokens := opts.MaxTokens
	if maxTokens <= 0 {
		maxTokens = 4096
	}

	var convo []openAIMessage
	if system != "" {
		convo = append(convo, openAIMessage{Role: "system", Content: system})
	}
	for _, m := range messages {
		convo = append(convo, openAIMessage{Role: m.Role, Content: m.Content})
	}

	openAITools := toOpenAITools(tools)
	var bestPlan, finalText string
	ranOutOfSteps := true

	for i := 0; i < maxSteps; i++ {
		req := openAIChatRequest{
			Model:       g.Model,
			Messages:    convo,
			Temperature: 0.0,
			MaxTokens:   maxTokens,
			Tools:       openAITools,
		}
		resp, err := g.doRequest(ctx, req, 300)
		if err != nil {
			return "", messages, err
		}
		choice := resp.Choices[0]
		text := strings.TrimSpace(choice.Message.Content)
		if looksLikePlan(text) && len(text) > len(bestPlan) {
			bestPlan = text
		}
		if text != "" {
			emitEvent(opts.OnEvent, domain.AgentEvent{Type: "output", Text: text})
		}
		for _, tc := range choice.Message.ToolCalls {
			var input map[string]any
			_ = json.Unmarshal([]byte(tc.Function.Arguments), &input)
			emitEvent(opts.OnEvent, domain.AgentEvent{Type: "tool", Name: tc.Function.Name, Input: input})
		}

		if len(choice.Message.ToolCalls) == 0 || choice.FinishReason != "tool_calls" {
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

		convo = append(convo, choice.Message)
		for _, tc := range choice.Message.ToolCalls {
			var input map[string]any
			_ = json.Unmarshal([]byte(tc.Function.Arguments), &input)
			result := executeTool(tc.Function.Name, input)
			truncated := result
			if len(truncated) > 200 {
				truncated = truncated[:200]
			}
			emitEvent(opts.OnEvent, domain.AgentEvent{Type: "tool_result", Text: truncated})
			convo = append(convo, openAIMessage{Role: "tool", ToolCallID: tc.ID, Content: result})
		}
	}
	if ranOutOfSteps {
		finalText = bestPlan
	}

	updated := append(append([]domain.Message{}, messages...), domain.Message{Role: "assistant", Content: finalText})
	return finalText, updated, nil
}
