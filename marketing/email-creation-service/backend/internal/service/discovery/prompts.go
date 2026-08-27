package discovery

import "strings"

// qaSection mirrors the `f"\nUser answers to clarifying questions:\n{qa}\n" if qa else ""`
// idiom (identical to audiencetools' own copy — Python duplicates this
// small snippet across both modules rather than sharing it).
func qaSection(qa string) string {
	if qa == "" {
		return ""
	}
	return "\nUser answers to clarifying questions:\n" + qa + "\n"
}

// BuildDiscoveryPrompt ports build_discovery_prompt verbatim.
func BuildDiscoveryPrompt(eventURL, qa string) string {
	prompt := strings.ReplaceAll(discoveryPromptTemplate, "__URL__", eventURL)
	prompt = strings.ReplaceAll(prompt, "__QA_SECTION__", qaSection(qa))
	return prompt
}
