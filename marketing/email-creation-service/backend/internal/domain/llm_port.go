package domain

import "context"

// Message is one turn in an agentic conversation, in the flattened text
// shape the CLI text-protocol backend needs (see dispatch/llm_claude_cli.go).
// SDK-backed adapters, when added, may need a richer content-block shape —
// that can be added as an alternative constructor without changing this
// port, since RunAgent callers only ever consume the returned text.
type Message struct {
	Role    string // "user" | "assistant"
	Content string
}

// ToolDef is the canonical tool definition shape (mirrors Anthropic's
// input_schema format used throughout llm/gateway.py) that every backend
// adapter must accept, so callers never special-case the active backend.
type ToolDef struct {
	Name        string
	Description string
	InputSchema map[string]any
}

// ExecuteToolFunc executes one tool call and returns a JSON-encoded result
// string, mirroring the Python execute_tool(name, input) -> str contract.
type ExecuteToolFunc func(name string, input map[string]any) string

// AgentEvent mirrors llm/gateway.py's on_event callback payloads, used to
// stream planning/content-generation progress to SSE consumers.
type AgentEvent struct {
	Type  string // "output" | "output_delta" | "tool" | "tool_result"
	Text  string
	Name  string
	Input map[string]any
}

// AgentEventFunc receives streamed AgentEvents. May be nil.
type AgentEventFunc func(AgentEvent)

// CompleteTextOptions parameterizes LLMGateway.CompleteText.
type CompleteTextOptions struct {
	System string
	// MaxTokens is a hint only for the CLI backend (which has no native
	// max_tokens knob); SDK backends, when added, will enforce it directly.
	MaxTokens int
	// TimeoutSeconds is a hard ceiling on the whole call.
	TimeoutSeconds int
	// IdleTimeoutSeconds, when non-zero, routes the CLI backend through the
	// streaming call so a turn that's still actively producing tokens isn't
	// killed just because total wall-clock exceeds TimeoutSeconds — only a
	// genuine stall (no output for this long) does. See
	// llm_claude_cli.go's callStreaming.
	IdleTimeoutSeconds int
	OnEvent            AgentEventFunc
}

// RunAgentOptions parameterizes LLMGateway.RunAgent.
type RunAgentOptions struct {
	MaxTokens int
	MaxSteps  int
	OnEvent   AgentEventFunc
}

// LLMGateway is the single port every service uses for LLM calls — mirrors
// llm/gateway.py's role as the one place a backend is chosen. Three
// backends implement this interface (dispatch/llm_claude_cli.go,
// llm_anthropic_sdk.go, llm_litellm.go); dispatch/llm_select.go picks one at
// startup with the same priority as Python's backend_name(): Anthropic API
// key present > LiteLLM configured > CLI fallback.
type LLMGateway interface {
	// CompleteText is a single-shot text completion (no tools).
	CompleteText(ctx context.Context, prompt string, opts CompleteTextOptions) (string, error)
	// RunAgent runs the agentic tool loop until the model produces a final
	// answer (no further tool call) or MaxSteps is exhausted. Returns the
	// final answer text and the updated message history.
	RunAgent(ctx context.Context, messages []Message, system string, tools []ToolDef, executeTool ExecuteToolFunc, opts RunAgentOptions) (string, []Message, error)
}

// RunCLISkillOptions parameterizes CLISkillRunner.RunCLISkill.
type RunCLISkillOptions struct {
	// Cwd, if set, is the working directory the CLI subprocess runs in —
	// mirrors run_cli_skill(cwd=...), used so the CLI's own MCP server
	// config (e.g. an Asana MCP server) resolves relative to the right
	// project directory.
	Cwd string
	// TimeoutSeconds is a hard ceiling on the whole call. Python defaults
	// this to 900.
	TimeoutSeconds int
	OnEvent        AgentEventFunc
	// StreamJSON mirrors run_cli_skill(stream_json=...): when true, adds
	// --output-format stream-json --include-partial-messages so OnEvent
	// receives incremental output; when false, the call is a flat blocking
	// wait with no partial-output streaming.
	StreamJSON bool
}

// CLISkillRunner is implemented only by the Claude CLI backend — mirrors
// llm/gateway.py's run_cli_skill, a mechanism distinct from RunAgent's
// TOOL_CALL:/TOOL_RESULT: text-protocol emulation: it does NOT pass
// --strict-mcp-config, so the CLI's own native MCP tool integrations (e.g.
// an Asana MCP server) are available, and it does a flat blocking wait
// rather than driving a tool-execution loop itself — the model is expected
// to use its native MCP tools directly. Python's fetch_asana_task_via_mcp
// is CLI-only regardless of which backend GET /api/status reports, so
// callers of this capability must obtain a *dispatch.ClaudeCLIGateway
// directly (or type-assert LLMGateway to this interface) rather than going
// through whichever backend llm_select.go chose for RunAgent/CompleteText.
type CLISkillRunner interface {
	RunCLISkill(ctx context.Context, prompt string, opts RunCLISkillOptions) (text string, success bool, err error)
}
