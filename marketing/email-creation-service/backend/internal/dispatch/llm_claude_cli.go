// Package dispatch's llm_claude_cli.go ports llm/gateway.py's CLI-fallback
// path (used whenever neither ANTHROPIC_API_KEY nor LITELLM_API_KEY/
// LITELLM_BASE_URL is set, which is the only backend actually exercised in
// this deployment today — no valid Anthropic key is ever configured here).
// The Anthropic-SDK (llm_anthropic_sdk.go) and LiteLLM (llm_litellm.go)
// adapters exist for source parity with llm/gateway.py's backend_name()
// priority and are selected by llm_select.go when their env vars are set.
package dispatch

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
)

// ClaudeCLIGateway implements domain.LLMGateway and domain.CLISkillRunner by
// shelling out to the `claude` CLI, mirroring llm/gateway.py's _cli_call /
// _cli_call_streaming / _agent_cli / run_cli_skill. This is the only backend
// actually reachable in this deployment (see package doc comment), but
// llm_anthropic_sdk.go and llm_litellm.go also implement domain.LLMGateway
// for source parity with backend_name()'s priority order.
type ClaudeCLIGateway struct {
	// Model is passed to every CLI invocation via --model, matching
	// llm/gateway.py's resolve_model() determinism guarantee (one model id
	// on every call).
	Model string
	// CLIPath overrides CLAUDE_CLI_PATH / PATH lookup when set (mainly for
	// tests). Empty means resolve lazily via resolveCLIPath.
	CLIPath string

	pathOnce sync.Once
	path     string
	pathErr  error
}

// NewClaudeCLIGateway builds a gateway targeting the given model id.
func NewClaudeCLIGateway(model string) *ClaudeCLIGateway {
	return &ClaudeCLIGateway{Model: model}
}

func (g *ClaudeCLIGateway) resolveCLIPath() (string, error) {
	g.pathOnce.Do(func() {
		if g.CLIPath != "" {
			g.path = g.CLIPath
			return
		}
		if env := os.Getenv("CLAUDE_CLI_PATH"); env != "" {
			g.path = env
			return
		}
		if found, err := exec.LookPath("claude"); err == nil {
			g.path = found
			return
		}
		const fallback = `C:\Users\VinayU\AppData\Roaming\npm\claude.cmd`
		if _, err := os.Stat(fallback); err == nil {
			g.path = fallback
			return
		}
		g.pathErr = fmt.Errorf("claude CLI not found: install with `npm install -g @anthropic-ai/claude-code`")
	})
	return g.path, g.pathErr
}

// cliArgv builds the base argv for a deterministic `claude --print` call —
// always pins --model, matching _cli_argv.
func (g *ClaudeCLIGateway) cliArgv(extra ...string) ([]string, error) {
	path, err := g.resolveCLIPath()
	if err != nil {
		return nil, err
	}
	argv := []string{path, "--print", "--model", g.Model, "--dangerously-skip-permissions"}
	return append(argv, extra...), nil
}

// killProcessTree kills the CLI subprocess (and, on Windows, its full
// process tree — CREATE_NEW_PROCESS_GROUP isn't available via os/exec, so
// taskkill /T is used the same way _kill's Windows branch does in Python).
func killProcessTree(cmd *exec.Cmd) {
	if cmd.Process == nil {
		return
	}
	if runtime.GOOS == "windows" {
		kill := exec.Command("taskkill", "/F", "/T", "/PID", strconv.Itoa(cmd.Process.Pid))
		_ = kill.Run()
		return
	}
	_ = cmd.Process.Kill()
}

// call is the non-streaming single blocking `claude --print` call via
// stdin, mirroring _cli_call. Returns stdout text.
func (g *ClaudeCLIGateway) call(prompt string, timeoutSeconds int) (string, error) {
	argv, err := g.cliArgv("--strict-mcp-config")
	if err != nil {
		return "", err
	}
	cmd := exec.Command(argv[0], argv[1:]...)
	cmd.Stdin = strings.NewReader(prompt)
	var stdout, stderr strings.Builder
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	if err := cmd.Start(); err != nil {
		return "", fmt.Errorf("start claude CLI: %w", err)
	}

	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()

	select {
	case err := <-done:
		if err != nil {
			stderrText := strings.TrimSpace(stderr.String())
			stdoutText := strings.TrimSpace(stdout.String())
			msg := stderrText
			if msg == "" {
				msg = stdoutText
			}
			if msg == "" {
				msg = err.Error()
			}
			return "", fmt.Errorf("claude CLI error: %s", msg)
		}
		return strings.TrimSpace(stdout.String()), nil
	case <-time.After(time.Duration(timeoutSeconds) * time.Second):
		killProcessTree(cmd)
		<-done
		return "", fmt.Errorf("claude CLI timed out after %ds", timeoutSeconds)
	}
}

// streamEvent mirrors the subset of `claude --output-format stream-json
// --include-partial-messages` event shapes callStreaming actually reads.
type streamEvent struct {
	Type  string `json:"type"`
	Event *struct {
		Type         string `json:"type"`
		ContentBlock *struct {
			Type string `json:"type"`
		} `json:"content_block"`
		Delta *struct {
			Type string `json:"type"`
			Text string `json:"text"`
		} `json:"delta"`
	} `json:"event"`
	Result string `json:"result"`
}

// callStreaming mirrors _cli_call_streaming: same contract as call (single
// `claude --print` turn, returns the full text) but streams text via
// on_event as the model generates it, and distinguishes "slow but still
// producing tokens" (idleTimeoutSeconds) from "actually hung"
// (timeoutSeconds hard ceiling) — see the Python docstring for why a flat
// wall-clock timeout alone kills legitimately-long turns.
func (g *ClaudeCLIGateway) callStreaming(prompt string, timeoutSeconds, idleTimeoutSeconds int, onEvent domain.AgentEventFunc) (string, error) {
	argv, err := g.cliArgv("--strict-mcp-config", "--output-format", "stream-json", "--include-partial-messages", "--verbose")
	if err != nil {
		return "", err
	}
	cmd := exec.Command(argv[0], argv[1:]...)
	stdin, err := cmd.StdinPipe()
	if err != nil {
		return "", err
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return "", err
	}
	var stderr strings.Builder
	cmd.Stderr = &stderr

	if err := cmd.Start(); err != nil {
		return "", fmt.Errorf("start claude CLI: %w", err)
	}
	go func() {
		_, _ = stdin.Write([]byte(prompt))
		_ = stdin.Close()
	}()

	var (
		mu           sync.Mutex
		textBuf      strings.Builder
		resultText   string
		lastActivity = time.Now()
		toolCallSeen bool
	)
	touch := func() {
		mu.Lock()
		lastActivity = time.Now()
		mu.Unlock()
	}
	idleFor := func() time.Duration {
		mu.Lock()
		defer mu.Unlock()
		return time.Since(lastActivity)
	}

	readerDone := make(chan struct{})
	go func() {
		defer close(readerDone)
		scanner := bufio.NewScanner(stdout)
		scanner.Buffer(make([]byte, 0, 64*1024), 16*1024*1024)
		for scanner.Scan() {
			line := strings.TrimSpace(scanner.Text())
			touch()
			if line == "" {
				continue
			}
			var ev streamEvent
			if err := json.Unmarshal([]byte(line), &ev); err != nil {
				continue
			}
			switch ev.Type {
			case "stream_event":
				if ev.Event == nil {
					continue
				}
				switch ev.Event.Type {
				case "content_block_start":
					if ev.Event.ContentBlock != nil && ev.Event.ContentBlock.Type == "thinking" {
						emitEvent(onEvent, domain.AgentEvent{Type: "output", Text: "🤔 thinking…"})
					}
				case "content_block_delta":
					if ev.Event.Delta != nil && ev.Event.Delta.Type == "text_delta" && ev.Event.Delta.Text != "" {
						emitEvent(onEvent, domain.AgentEvent{Type: "output_delta", Text: ev.Event.Delta.Text})
						mu.Lock()
						textBuf.WriteString(ev.Event.Delta.Text)
						current := textBuf.String()
						mu.Unlock()
						// Stop as soon as a complete tool call has been written —
						// see _extract_tool_call's doc comment for why the model
						// is not trusted to stop on its own.
						if _, _, ok := extractToolCall(current); ok {
							toolCallSeen = true
							return
						}
					}
				}
			case "result":
				resultText = ev.Result
			}
		}
	}()

	deadline := time.Now().Add(time.Duration(timeoutSeconds) * time.Second)
	ticker := time.NewTicker(200 * time.Millisecond)
	defer ticker.Stop()
	waitCh := make(chan error, 1)
	go func() { waitCh <- cmd.Wait() }()

	for {
		select {
		case <-readerDone:
			if toolCallSeen {
				killProcessTree(cmd)
				<-waitCh
				mu.Lock()
				out := textBuf.String()
				mu.Unlock()
				return strings.TrimSpace(out), nil
			}
			// Reader hit EOF without a tool call — wait for process exit.
			err := <-waitCh
			if toolCallSeen {
				mu.Lock()
				out := textBuf.String()
				mu.Unlock()
				return strings.TrimSpace(out), nil
			}
			if err != nil {
				stderrText := strings.TrimSpace(stderr.String())
				if stderrText == "" {
					stderrText = err.Error()
				}
				return "", fmt.Errorf("claude CLI error: %s", stderrText)
			}
			return strings.TrimSpace(resultText), nil
		case <-ticker.C:
			if idleFor() > time.Duration(idleTimeoutSeconds)*time.Second {
				killProcessTree(cmd)
				<-readerDone
				<-waitCh
				return "", fmt.Errorf("claude CLI idle for %ds with no output — likely hung", idleTimeoutSeconds)
			}
			if time.Now().After(deadline) {
				killProcessTree(cmd)
				<-readerDone
				<-waitCh
				return "", fmt.Errorf("claude CLI exceeded %ds hard timeout", timeoutSeconds)
			}
		}
	}
}

func emitEvent(onEvent domain.AgentEventFunc, ev domain.AgentEvent) {
	if onEvent == nil {
		return
	}
	defer func() { _ = recover() }()
	onEvent(ev)
}

// extractToolCall finds the FIRST `TOOL_CALL:` marker and returns
// (jsonPayload, truncatedText, true) — truncatedText is text cut off right
// after that JSON, discarding anything the model wrote afterward. Mirrors
// _extract_tool_call, including its brace-depth matching (tolerates
// pretty-printed/indented nested JSON) and its rationale: the model
// routinely keeps generating past one TOOL_CALL (fabricating its own
// TOOL_RESULT, or repeating itself), so truncating here — and never
// trusting anything past the matched brace — is what keeps hallucinated
// data out of the next turn.
func extractToolCall(text string) (jsonPayload string, truncated string, ok bool) {
	lines := strings.Split(text, "\n")
	markerIdx := -1
	for i, l := range lines {
		if strings.HasPrefix(strings.TrimSpace(l), "TOOL_CALL:") {
			markerIdx = i
			break
		}
	}
	if markerIdx == -1 {
		return "", "", false
	}
	tail := strings.TrimSpace(strings.TrimPrefix(strings.TrimSpace(lines[markerIdx]), "TOOL_CALL:"))
	rest := strings.Join(append([]string{tail}, lines[markerIdx+1:]...), "\n")

	depth := 0
	start := -1
	for i, ch := range rest {
		switch ch {
		case '{':
			if depth == 0 {
				start = i
			}
			depth++
		case '}':
			depth--
			if depth == 0 && start != -1 {
				jsonStr := rest[start : i+1]
				truncatedLines := append(append([]string{}, lines[:markerIdx]...), "TOOL_CALL: "+jsonStr)
				return jsonStr, strings.Join(truncatedLines, "\n"), true
			}
		}
	}
	return "", "", false
}

// toolsToCLIInstructions renders a tool listing for the CLI text-protocol
// path, mirroring _tools_to_cli_instructions.
func toolsToCLIInstructions(tools []domain.ToolDef) string {
	lines := make([]string, 0, len(tools))
	for _, t := range tools {
		props, _ := t.InputSchema["properties"].(map[string]any)
		required := map[string]bool{}
		if req, ok := t.InputSchema["required"].([]any); ok {
			for _, r := range req {
				if s, ok := r.(string); ok {
					required[s] = true
				}
			}
		}
		params := make([]string, 0, len(props))
		for p := range props {
			if required[p] {
				params = append(params, p)
			} else {
				params = append(params, p+"?")
			}
		}
		desc := strings.TrimSpace(t.Description)
		if len(desc) > 120 {
			desc = desc[:120]
		}
		lines = append(lines, fmt.Sprintf("  %s(%s) — %s", t.Name, strings.Join(params, ", "), desc))
	}
	return strings.Join(lines, "\n")
}

const cliAgentRules = `
IMPORTANT: You are operating in EXECUTION MODE. Do NOT enter plan mode. Do NOT ask for approval.
Execute tool calls immediately and directly.

To call a tool output EXACTLY this on its own line (nothing else on that line):
  TOOL_CALL: {"name": "<tool>", "input": {<params>}}

Available tools:
%s

Tool results are returned as:
  TOOL_RESULT: {<json>}

Rules:
- Call tools immediately without asking for confirmation
- Do NOT say "I'll now...", "Let me...", or "I plan to..." — just output the TOOL_CALL line
- Output EXACTLY ONE ` + "`TOOL_CALL:`" + ` line, then STOP — do not keep generating. You will
  never see the real result until the system sends you a ` + "`TOOL_RESULT:`" + ` in the NEXT
  turn — writing your own ` + "`TOOL_RESULT:`" + ` (or a second ` + "`TOOL_CALL:`" + `) is not real data,
  it's you guessing, and guessed data breaks the workflow.
- When all tools are done, write your final response to the user
`

func looksLikePlan(text string) bool {
	return strings.Contains(text, "##") || strings.Contains(text, "|---|") || strings.Contains(text, "| **") || len(text) > 400
}

// stripProtocol drops TOOL_CALL/TOOL_RESULT protocol lines — they are not
// user-facing, mirroring _agent_cli's _strip_protocol.
func stripProtocol(text string) string {
	lines := strings.Split(text, "\n")
	kept := make([]string, 0, len(lines))
	for _, l := range lines {
		trimmed := strings.TrimSpace(l)
		if strings.HasPrefix(trimmed, "TOOL_CALL:") || strings.HasPrefix(trimmed, "TOOL_RESULT:") {
			continue
		}
		kept = append(kept, l)
	}
	return strings.TrimSpace(strings.Join(kept, "\n"))
}

// CompleteText implements domain.LLMGateway.
func (g *ClaudeCLIGateway) CompleteText(ctx context.Context, prompt string, opts domain.CompleteTextOptions) (string, error) {
	full := prompt
	if opts.System != "" {
		full = fmt.Sprintf("<system>\n%s\n</system>\n\n%s", opts.System, prompt)
	}
	timeout := opts.TimeoutSeconds
	if timeout <= 0 {
		timeout = 120
	}
	if opts.IdleTimeoutSeconds > 0 {
		return g.callStreaming(full, timeout, opts.IdleTimeoutSeconds, opts.OnEvent)
	}
	return g.call(full, timeout)
}

// RunAgent implements domain.LLMGateway, mirroring _agent_cli: builds a
// text-protocol prompt (recent history + tool listing + rules), loops
// callStreaming -> extractToolCall -> executeTool -> feed back TOOL_RESULT
// until a turn produces no tool call or maxSteps is exhausted, tracking the
// richest plan-like text seen along the way as a fallback for a thin final
// turn (mirrors best_plan in Python).
func (g *ClaudeCLIGateway) RunAgent(ctx context.Context, messages []domain.Message, system string, tools []domain.ToolDef, executeTool domain.ExecuteToolFunc, opts domain.RunAgentOptions) (string, []domain.Message, error) {
	maxSteps := opts.MaxSteps
	if maxSteps <= 0 {
		maxSteps = 8
	}

	var historyLines []string
	visible := messages
	if len(visible) > 6 {
		visible = visible[len(visible)-6:]
	}
	for _, m := range visible {
		role := "Assistant"
		if m.Role == "user" {
			role = "User"
		}
		historyLines = append(historyLines, fmt.Sprintf("%s: %s\n", role, m.Content))
	}

	rules := fmt.Sprintf(cliAgentRules, toolsToCLIInstructions(tools))
	prompt := fmt.Sprintf("<system>\n%s\n</system>\n\n%s\n\nConversation history:\n%s", system, rules, strings.Join(historyLines, "\n"))

	var bestPlan, finalText string
	ranOutOfSteps := true
	for i := 0; i < maxSteps; i++ {
		// idleTimeout=90 kills a truly-stalled call; timeout=300 is just a
		// backstop against a pathological turn that never stops generating —
		// same constants as _agent_cli.
		response, err := g.callStreaming(prompt, 300, 90, opts.OnEvent)
		if err != nil {
			return "", messages, err
		}

		nonTool := stripProtocol(response)
		if looksLikePlan(nonTool) && len(nonTool) > len(bestPlan) {
			bestPlan = nonTool
		}

		if jsonPayload, truncated, ok := extractToolCall(response); ok {
			var call struct {
				Name  string         `json:"name"`
				Input map[string]any `json:"input"`
			}
			var result string
			if err := json.Unmarshal([]byte(jsonPayload), &call); err != nil {
				resultBytes, _ := json.Marshal(map[string]string{"error": err.Error()})
				result = string(resultBytes)
			} else {
				emitEvent(opts.OnEvent, domain.AgentEvent{Type: "tool", Name: call.Name, Input: call.Input})
				result = executeTool(call.Name, call.Input)
				truncatedResult := result
				if len(truncatedResult) > 200 {
					truncatedResult = truncatedResult[:200]
				}
				emitEvent(opts.OnEvent, domain.AgentEvent{Type: "tool_result", Text: truncatedResult})
			}
			prompt += fmt.Sprintf("\n%s\nTOOL_RESULT: %s\n", truncated, result)
			continue
		}

		// No tool call → final answer. Use it if it carries the plan;
		// otherwise fall back to the richest intermediate plan.
		if looksLikePlan(nonTool) {
			finalText = nonTool
		} else if bestPlan != "" {
			finalText = bestPlan
		} else {
			finalText = nonTool
		}
		ranOutOfSteps = false
		break
	}
	if ranOutOfSteps {
		finalText = bestPlan
	}

	updated := append(append([]domain.Message{}, messages...), domain.Message{Role: "assistant", Content: finalText})
	return finalText, updated, nil
}

// RunCLISkill implements domain.CLISkillRunner, mirroring run_cli_skill: a
// CLI invocation distinct from call/callStreaming's TOOL_CALL: emulation —
// no --strict-mcp-config (the CLI's own real MCP tool integrations, e.g. an
// Asana MCP server, stay available), a flat blocking wait with no idle
// timeout, and a plain (text, success) result rather than driving a tool
// loop here (the model is expected to invoke its native MCP tools itself).
func (g *ClaudeCLIGateway) RunCLISkill(ctx context.Context, prompt string, opts domain.RunCLISkillOptions) (string, bool, error) {
	extra := []string{}
	if opts.StreamJSON {
		extra = append(extra, "--output-format", "stream-json", "--include-partial-messages", "--verbose")
	}
	argv, err := g.cliArgv(extra...)
	if err != nil {
		return "", false, err
	}
	cmd := exec.Command(argv[0], argv[1:]...)
	if opts.Cwd != "" {
		cmd.Dir = opts.Cwd
	}
	cmd.Stdin = strings.NewReader(prompt)
	var stdout, stderr strings.Builder
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	timeout := opts.TimeoutSeconds
	if timeout <= 0 {
		timeout = 900
	}

	if err := cmd.Start(); err != nil {
		return "", false, fmt.Errorf("start claude CLI: %w", err)
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()

	select {
	case err := <-done:
		out := strings.TrimSpace(stdout.String())
		if opts.OnEvent != nil && out != "" {
			emitEvent(opts.OnEvent, domain.AgentEvent{Type: "output", Text: out})
		}
		if err != nil {
			return out, false, nil
		}
		return out, true, nil
	case <-time.After(time.Duration(timeout) * time.Second):
		killProcessTree(cmd)
		<-done
		return "", false, fmt.Errorf("claude CLI (skill) timed out after %ds", timeout)
	case <-ctx.Done():
		killProcessTree(cmd)
		<-done
		return "", false, ctx.Err()
	}
}
